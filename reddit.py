from electroncash.util import PrintError, print_error, age, Weak, InvalidPassword
from electroncash.address import Address
from electroncash.exchange_rate import *
from electroncash.wallet import Abstract_Wallet
from electroncash_gui.qt.util import webopen, MessageBoxMixin
from electroncash.i18n import _

from decimal import Decimal
import datetime
import traceback
import re
import random
import socket
import sys

from PyQt5.QtCore import QObject, pyqtSignal, QThread
from PyQt5.QtWidgets import QApplication, QMessageBox
from PyQt5.QtGui import QIcon

from .model import Tip, TipList
from .config import c, amount_config
from .util import read_config, write_config, has_config

# praw and prawcore are being imported in this "top-level"-way to avoid loading lower modules which will fail as external plugins
from . import praw
from . import prawcore

class WalletStorageTokenManager(praw.util.token_manager.BaseTokenManager, PrintError):
	"""praw TokenManager to manage storage of reddit refresh token into wallet file"""
	ACCESS_TOKEN_KEY = "reddit_access_token"
	REFRESH_TOKEN_KEY = "reddit_refresh_token"
	def __init__(self, wallet: Abstract_Wallet):
		praw.util.token_manager.BaseTokenManager.__init__(self)
		self.wallet = wallet

	def post_refresh_callback(self, authorizer):
		self.print_error("post_refresh_callback(), refresh_token: ", authorizer.refresh_token)
		write_config(self.wallet, WalletStorageTokenManager.ACCESS_TOKEN_KEY, authorizer.access_token)
		write_config(self.wallet, WalletStorageTokenManager.REFRESH_TOKEN_KEY, authorizer.refresh_token)

	def pre_refresh_callback(self, authorizer):
		self.print_error("pre_refresh_callback()")
		if self.has_refresh_token():
			authorizer.refresh_token = read_config(self.wallet, WalletStorageTokenManager.REFRESH_TOKEN_KEY, authorizer.refresh_token)

	def has_refresh_token(self):
		return has_config(self.wallet, WalletStorageTokenManager.REFRESH_TOKEN_KEY)

class Reddit(PrintError, QObject):
	"""implement reddit client to read new inbox messages, parse tip comments and so on
	authorization stuff was largely taken from https://praw.readthedocs.io/en/latest/tutorials/refresh_token.html#using-refresh-tokens
	"""
	new_tip = pyqtSignal(Tip)

	def __init__(self, wallet_ui):
		QObject.__init__(self)
		self.wallet_ui = wallet_ui
		self.should_quit = False
		self.state = None # used in reddit auth flow
		self.tips_to_refresh = []
		self.tips_to_mark_read = []

	def receive_connection(self, port):
		"""Wait for and then return a connected socket..
		Opens a TCP connection on port 'port', and waits for a single client.
		"""
		server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
		server.bind(("localhost", port))
		server.listen(1)
		client = server.accept()[0]
		server.close()
		return client

	def send_message(self, client, message):
		"""Send message to client and close the connection."""
		message = """
		<html><body>
			<script type="text/javascript">
			  window.close() ;
			</script>
		""" + message + """
		<br><br>You can close this tab.
		</body></html>
		"""
		client.send(f"HTTP/1.1 200 OK\r\n\r\n{message}".encode("utf-8"))
		client.close()

	def login(self):
		#authentication_mode = read_config(self.wallet_ui.wallet, "reddit_authentication_mode", "credentials")
		authentication_mode = "app"
		user_agent = c["reddit"]["user_agent"]
		try:
			if authentication_mode == "credentials":
				self.reddit = praw.Reddit(
						client_id=c["reddit"]["script_client_id"],
						client_secret=c["reddit"]["script_client_secret"],
						user_agent = user_agent,
						username = read_config(self.wallet_ui.wallet, "reddit_username"),
						password = read_config(self.wallet_ui.wallet, "reddit_password"),
				)
			elif authentication_mode == "app":
				#redirect_uri = c["reddit"]["redirect_uri"]
				self.token_manager = WalletStorageTokenManager(self.wallet_ui.wallet)
				port = 18763
				scopes = ["privatemessages","read"]

				redirect_uri = "http://localhost:" + str(c["reddit"]["local_auth_server_port"])
				self.reddit = praw.Reddit(
					client_id = c["reddit"]["client_id"],
					client_secret = None,
					redirect_uri = redirect_uri,
					user_agent = user_agent,
					token_manager = self.token_manager
				)

				# probe if current refresh token (if exists) works
				login_ok = False
				if self.token_manager.has_refresh_token():
					try:
						authenticated_scopes = self.reddit.auth.scopes()
						self.print_error("scopes of authenticated user:", authenticated_scopes)
						login_ok = True
					except Exception as e:
						self.print_error("refresh token doesn't work, error: ", e)
						# refresh token unusable, reset it
						write_config(self.wallet_ui.wallet, WalletStorageTokenManager.REFRESH_TOKEN_KEY, None)

				# no stored refresh token => we need to send user to browser to authorize chaintipper app
				if not self.token_manager.has_refresh_token():
					self.print_error("acquiring new refresh token by sending user's browser to reddit app setup and listening for redirect on localhost")
					self.state = str(random.randint(0, 65000))
					url = self.reddit.auth.url(scopes, self.state, "permanent")

					choice = self.wallet_ui.window.msg_box(
						icon = QMessageBox.Question,
						parent = self.wallet_ui.window,
						title = _("ChainTipper Reddit Authorization"),
						rich_text = True,
						text = "".join([
							"<h3>", _("Let's connect to your reddit account."), "</h3>",
							_("To do this we need to open a web browser so you can authorize the 'chaintipper' app."),
							"<br><br>", _("ChainTipper will request the following permissions: "),
							"<ul>",
							"<li><b>", _("Private Messages"), "</b>: ", _("Access my inbox and send private messages to other users."), "</li>",
							"<li><b>", _("Read"), "</b>: ", _("Access posts and comments through my account."), "</li>",
							"</ul>"
							"<small>", _("Note: unfortunately there is no read-only permission for private messages. ChainTipper doesn't write messages."), "</small>"
						]),
						buttons = (_("Open Browser"), _("Cancel")),
						defaultButton = _("Open Browser"),
						escapeButton = _("Cancel")
					)
					if choice == 1: # Cancel
						return False

					webopen(url)

					return True # pretend login was complete and await refresh token in reddit thread

				# test login (provoking exception on fail)
				authenticated_scopes = self.reddit.auth.scopes()
				self.print_error("scopes of authenticated user:", authenticated_scopes)

			# authentication successful
			return True

		except prawcore.exceptions.PrawcoreException as e:
			# authentication failed somehow
			self.print_error(e)
			return False

	def await_reddit_authorization(self):
		"""this blocks until users browser redirects to our makeshift server on localhost"""
		if self.state: 
			client = self.receive_connection(c["reddit"]["local_auth_server_port"])
			data = client.recv(1024).decode("utf-8")
			param_tokens = data.split(" ", 2)[1].split("?", 1)[1].split("&")
			params = {
				key: value for (key, value) in [token.split("=") for token in param_tokens]
			}

			if self.state != params["state"]:
				self.send_message(
					client,
					f"State mismatch. Expected: {state} Received: {params['state']}",
				)
				return False
			elif "error" in params:
				self.send_message(client, f'Authorization failed with "{params["error"]}".<br><br>Chaintipper will deactivate.')
				return False

			#msgbox.close()
			refresh_token = self.reddit.auth.authorize(params["code"])
			self.print_error("refresh_token: ", refresh_token)
			self.send_message(client, f"Refresh token: {refresh_token}<br><br>Chaintipper should now be connected to your Reddit Account")

			# store refresh token into wallet storage (wonder why praw doesn't call token manager to do this)
			write_config(self.wallet_ui.wallet, WalletStorageTokenManager.REFRESH_TOKEN_KEY, refresh_token)

	def triggerRefreshTips(self):
		self.tips_to_refresh += [tip for tip in self.wallet_ui.tiplist.tips.values()]

	def refreshTips(self):
		while len(self.tips_to_refresh) > 0:
			tip = self.tips_to_refresh.pop()
			self.print_error("refreshing ", tip)
			self.wallet_ui.tiplist.removeTip(tip)
			tip.refresh()
			self.wallet_ui.tiplist.addTip(tip)

	def triggerMarkRead(self, tips):
		self.tips_to_mark_read += tips

	def markReadTips(self):
		while len(self.tips_to_mark_read):
			tip = self.tips_to_mark_read.pop()
			tip.chaintip_message.mark_read()
			self.wallet_ui.tiplist.removeTip(tip)

	def disconnect(self):
		write_config(self.wallet_ui.wallet, WalletStorageTokenManager.ACCESS_TOKEN_KEY, None)
		write_config(self.wallet_ui.wallet, WalletStorageTokenManager.REFRESH_TOKEN_KEY, None)

	def quit(self):
		self.should_quit = True
		if hasattr(self, "dathread"):
			self.dathread.quit()

	def start_thread(self):
		self.dathread = QThread()
		self.moveToThread(self.dathread)
		self.dathread.started.connect(self.run)
		self.dathread.start()

	def run(self):
		self.print_error("Reddit.run() called")
		tips = []

		self.await_reddit_authorization()

		try:
			for item in self.reddit.inbox.stream(pause_after=0):
				# some "background tasks"
				self.refreshTips()
				self.markReadTips()

				# digest item
				if self.should_quit:
					break
				if item is None:
					continue
				if isinstance(item, praw.models.Message):
					tip = RedditTip(self, item)
					if tip.isValid():
						if not self.should_quit:
							self.new_tip.emit(tip)
				if isinstance(item, praw.models.Comment):
					continue
		except prawcore.exceptions.PrawcoreException as e:
			self.print_error("exception in reddit inbox streaming: ", e)

		self.print_error("exited reddit inbox streaming")

		self.dathread.quit()

class RedditTip(PrintError, Tip):

	p_subject = re.compile('Tip (\S*)')
	p_tip_comment = re.compile('.*\[your tip\]\(\S*/_/(\S*)\).*', re.MULTILINE | re.DOTALL)
	p_recipient = re.compile('^u/(\S*) has.*by sending Bitcoin Cash \(BCH\) to: \*\*(bitcoincash:q\w*)\*\*.*', re.MULTILINE | re.DOTALL)
	p_sender = re.compile('^u/(\S*) has just sent you (\S*) Bitcoin Cash \(about \S* USD\) \[via\]\(\S*/_/(\S*)\) .*', re.MULTILINE | re.DOTALL)

	def __init__(self, reddit: Reddit, message: praw.models.Message):
		Tip.__init__(self)
		self.platform = "reddit"
		self.reddit = reddit

		self.chaintip_message = message

		self.parseChaintipMessage()

	# Tip overrides

	def getID(self):
		return self.tipping_comment_id

	def refresh(self):
		if self.payment_status != 'paid':
			self.parseChaintipMessage()

	#

	def isValid(self):
		 return \
			self.is_chaintip and \
			self.chaintip_message and \
			self.chaintip_message.author == 'chaintip' and \
			self.type == 'send' 

	def parseChaintipMessage(self):
		self.is_chaintip = False
		self.type = None
		self.default_amount_used = False

		message = self.chaintip_message
		self.id = message.id
		self.subject = message.subject

		# parse chaintip message
		if hasattr(self.chaintip_message.author, "name") and self.chaintip_message.author.name == 'chaintip':
			self.is_chaintip = True
			#self.print_error(f"parsing chaintip message {message.id}")

			# receive tip message
			if self.chaintip_message.subject == "You've been tipped!":
				m = RedditTip.p_sender.match(self.chaintip_message.body)
				if m:
					self.type = 'receive'
					self.username = m.group(1)
					self.direction = 'incoming'
					self.amount_bch = Decimal(m.group(2))
					self.print_error("p_sender matches, user: ", self.username)
				else:
					self.print_error("p_sender doesn't match")

			# match outgoing tip
			m = RedditTip.p_subject.match(self.chaintip_message.subject)
			if m:
				m = RedditTip.p_tip_comment.match(self.chaintip_message.body)
				if m:
					self.type = 'send'
					self.tipping_comment_id = m.group(1)
					self.direction = 'outgoing'
				m = RedditTip.p_recipient.match(self.chaintip_message.body)
				if m:
					self.username = m.group(1)
					self.recipient_address = Address.from_cashaddr_string(m.group(2))

			# fetch tipping comment
			if self.tipping_comment_id:
				comment = self.reddit.reddit.comment(id = self.tipping_comment_id)
				self.parseTippingComment(comment)

	p_tip = re.compile('.*(u/chaintip (\S*)\s*(\S*))', re.MULTILINE | re.DOTALL)
	def parseTippingComment(self, comment):
		#self.print_error("got tipping comment:", comment.body)
		self.tipping_comment = comment
		self.subreddit_str = "r/" + self.tipping_comment.subreddit.display_name
		m = RedditTip.p_tip.match(self.tipping_comment.body)
		self.tip_unit = ''
		if m:
			try:
				self.tip_amount_text = m.group(1)
				if not m.group(3): # <tip_unit>
					self.tip_unit = m.group(3)
					self.tip_quantity = Decimal("1")
				else: # <tip_quantity> <tip_unit>
					try:
						self.tip_quantity = amount_config["quantity_aliases"][m.group(2)]
					except Exception as e:
						self.tip_quantity = Decimal(m.group(2))
					self.tip_unit = m.group(3)
					# <onchain_message>
					# if m.lastindex >= 3:
					# 	self.tip_op_return = m.group(3)
				self.evaluateAmount()
			except Exception as e:
				self.print_error("Error parsing tip amount: ", repr(e))
				traceback.print_exc()
				self.payment_status = 'ready to pay'
				self.amount_bch = self.getDefaultAmountBCH()
				self.default_amount_used = True
		else: # use default amount
			self.payment_status = 'ready to pay'
			self.amount_bch = self.getDefaultAmountBCH()
			self.default_amount_used = True

		self.qualifiesForAutopay() # will update payment_status

	def evaluateAmount(self):
		# in case all else fails, use default amount
		self.amount_bch = self.getDefaultAmountBCH()
		self.default_amount_used = True

		# find unit from amount config
		matching_units = (unit for unit in amount_config["units"] if self.tip_unit in unit["names"])
		unit = next(matching_units, None)
		if unit:
			rate = self.getRate(unit["value_currency"])
			self.amount_bch = round(self.tip_quantity * unit["value"] / rate, 8)
			self.default_amount_used = False
			#self.print_error("found unit", unit, "value", unit["value"], "quantity", self.tip_quantity, "rate", rate)
			self.payment_status = 'ready to pay'
		else:		
			# try tip_unit as currency 
			rate = self.getRate(self.tip_unit)
			self.amount_bch = round(self.tip_quantity / rate, 8)
			self.default_amount_used = False
			#self.print_error("rate for tip_unit", self.tip_unit, ": ", rate)
			self.payment_status = 'ready to pay'

		# if self.payment_status == 'ready to pay':
		# 	autopay_use_limit = read_config(self.wallet, "autopay_use_limit", c["default_autopay_use_limit"])
		# 	autopay_limit_bch = Decimal(read_config(self.wallet, "autopay_limit_bch", c["default_autopay_limit_bch"]))
		# 	if autopay_use_limit and autopay_limit_bch < self.amount_bch:
		# 		self.payment_status = 'autopay limited'
			
	def getDefaultAmountBCH(self):
		wallet = self.reddit.wallet_ui.wallet
		amount = Decimal(read_config(wallet, "default_amount", c["default_amount"]))
		currency = read_config(wallet, "default_amount_currency", c["default_amount_currency"])
		rate = self.getRate(currency)
		amount_bch = round(amount / rate, 8)
		return amount_bch

	def getRate(self, ccy: str):
		ccy = ccy.upper()
		if ccy == 'BCH':
			rate = Decimal("1.0")
		else:
			exchanges_by_ccy = get_exchanges_by_ccy(False)
			#self.print_error("exchanges: ", exchanges_by_ccy)
			exchanges = exchanges_by_ccy[ccy]
			#self.print_error("exchanges: ", exchanges)
			exchange_name = exchanges[0]
			klass = globals()[exchange_name]
			exchange = klass(None, None)
			#self.print_error("exchange: ", exchange)
			rate = exchange.get_rates(ccy)[ccy]
			#self.print_error("rate", rate)
		return rate

	def qualifiesForAutopay(self):
		wallet = self.reddit.wallet_ui.wallet

		if self.payment_status != 'ready to pay': return False

		# recipient_address set?
		if \
			self.recipient_address == None or \
			not isinstance(self.recipient_address, Address) \
		:
			self.payment_status = 'invalid recipient address'
			return False

		# autopay activated?
		if not read_config(wallet, "autopay", c["default_autopay"]): 
			self.payment_status = 'autopay disabled'
			return False		

		# default amount disallowed?
		if read_config(wallet, "autopay_disallow_default", c["default_autopay_disallow_default"]) \
			and self.default_amount_used \
		: 
			self.payment_status = 'autopay default amount disallowed'
			return False

		# amount limit exceeded?
		autopay_use_limit = read_config(wallet, "autopay_use_limit", c["default_autopay_use_limit"])
		autopay_limit_bch = Decimal(read_config(wallet, "autopay_limit_bch", c["default_autopay_limit_bch"]))
		if autopay_use_limit and self.amount_bch > autopay_limit_bch: 
			self.payment_status = "autopay amount-limited"
			return False

		return True
