from electroncash.util import PrintError, print_error, age, Weak, InvalidPassword, format_time
from electroncash.address import Address
from electroncash.exchange_rate import *
from electroncash.wallet import Abstract_Wallet
from electroncash_gui.qt.util import webopen, MessageBoxMixin
from electroncash.i18n import _
from electroncash.network import Network

from decimal import Decimal
from datetime import datetime
import traceback
import re
import random
import socket
import sys
from time import time, sleep
from collections import defaultdict

from PyQt5.QtCore import QObject, pyqtSignal, QThread
from PyQt5.QtWidgets import QApplication, QMessageBox
from PyQt5.QtGui import QIcon

from .model import Tip, TipList
from .config import c, amount_config
from .util import read_config, write_config, has_config

# praw and prawcore are being imported in this "top-level"-way to avoid loading lower modules which will fail as external plugins
from . import praw
from . import prawcore
from . import iterators


############################################################################################################################
#                                                                                                                          #
#     ad88888ba                                                                88b           d88                           #
#    d8"     "8b ,d                                                            888b         d888                           #
#    Y8,         88                                                            88`8b       d8'88                           #
#    `Y8aaaaa, MM88MMM ,adPPYba,  8b,dPPYba, ,adPPYYba,  ,adPPYb,d8  ,adPPYba, 88 `8b     d8' 88 ,adPPYYba, 8b,dPPYba,     #
#      `"""""8b, 88   a8"     "8a 88P'   "Y8 ""     `Y8 a8"    `Y88 a8P_____88 88  `8b   d8'  88 ""     `Y8 88P'   `"8a    #
#            `8b 88   8b       d8 88         ,adPPPPP88 8b       88 8PP""""""" 88   `8b d8'   88 ,adPPPPP88 88       88    #
#    Y8a     a8P 88,  "8a,   ,a8" 88         88,    ,88 "8a,   ,d88 "8b,   ,aa 88    `888'    88 88,    ,88 88       88    #
#     "Y88888P"  "Y888 `"YbbdP"'  88         `"8bbdP"Y8  `"YbbdP"Y8  `"Ybbd8"' 88     `8'     88 `"8bbdP"Y8 88       88    #
#                                                        aa,    ,88                                                        #
#                                                         "Y8bbdP"                                                         #
############################################################################################################################

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




##################################################################
#                                                                #
#    88888888ba                     88          88 88            #
#    88      "8b                    88          88 ""   ,d       #
#    88      ,8P                    88          88      88       #
#    88aaaaaa8P' ,adPPYba,  ,adPPYb,88  ,adPPYb,88 88 MM88MMM    #
#    88""""88'  a8P_____88 a8"    `Y88 a8"    `Y88 88   88       #
#    88    `8b  8PP""""""" 8b       88 8b       88 88   88       #
#    88     `8b "8b,   ,aa "8a,   ,d88 "8a,   ,d88 88   88,      #
#    88      `8b `"Ybbd8"'  `"8bbdP"Y8  `"8bbdP"Y8 88   "Y888    #
#                                                                #
#                                                                #
##################################################################

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
		self.tip_or_message_by_message = dict()
		self.unassociated_claim_return_by_tipping_comment_id = defaultdict(list) # store claim/return info (dict with "message" and "action") for later association with a tip
		self.unassociated_chaintip_comments_by_tipping_comment_id = {} # store chaintip comments for later association with a tip
		self.items_by_fullname = {}

	def debug_stats(self):
		return f"\
            Reddit: {len(self.unassociated_chaintip_comments_by_tipping_comment_id)} unassociated chaintip comments\n\
                       {sum([len(i) for i in self.unassociated_claim_return_by_tipping_comment_id.values()])} unassociated claim/returned messages\n\
                       {len(self.items_by_fullname)} items registered"

	def disconnect(self):
		write_config(self.wallet_ui.wallet, WalletStorageTokenManager.ACCESS_TOKEN_KEY, None)
		write_config(self.wallet_ui.wallet, WalletStorageTokenManager.REFRESH_TOKEN_KEY, None)

	def quit(self):
		self.should_quit = True
		if hasattr(self, "dathread"):
			self.dathread.quit()

	def start_thread(self):
		self.dathread = QThread()
		self.dathread.setObjectName("reddit_thread")
		self.moveToThread(self.dathread)
		self.dathread.started.connect(self.run)
		self.dathread.start()

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

	p_context = re.compile('(/r.*/\w*/.*/)\w*/\?context=3', re.DOTALL)
	def getCommentLink(self, comment):
		if hasattr(comment, "permalink") and comment.permalink:
			return comment.permalink
		# construct link from context	
		m = Reddit.p_context.match(comment.context)
		if m:
			return m.group(1) + comment.id
		return None

	def triggerRefreshTips(self):
		if hasattr(self.wallet_ui, "tiplist"):
			self.tips_to_refresh += [tip for tip in self.wallet_ui.tiplist.tips.values()]

	def refreshTips(self):
		while len(self.tips_to_refresh) > 0:
			tip = self.tips_to_refresh.pop()
			self.print_error("refreshing", tip)
			tip.refreshAmount()

	def transition_amount_set_2_ready_to_pay(self):
		network = Network.get_instance()
		offline = not network
		if not hasattr(self.wallet_ui, "tiplist") or self.wallet_ui.tiplist is None:
			return
		for tip in self.wallet_ui.tiplist.tips.values():
			if tip.payment_status and tip.payment_status[:10] == 'amount set':
				if offline:
					tip.amount_set_time = time()
				else:
					secs = int(time() - tip.amount_set_time)
					if secs > c["ready_to_pay_grace_secs"]:
						tip.payment_status = "ready to pay"
						# reset autopay timer to improve batching (wait for more tips to become ready to pay)
						if self.wallet_ui.autopay:
							self.wallet_ui.autopay.resetTimer() 
					else:
						tip.payment_status = f'amount set ({secs}s)' 
					tip.update()

	p_mark_1 = re.compile('u/(\S*) has not yet linked an address\.', re.MULTILINE | re.DOTALL)
	p_mark_2 = re.compile('Unfortunately, this .* bot is unable to understand your message\..*', re.MULTILINE | re.DOTALL)
	def markChaintipMessagesUnread(self, limit):
		items = []
		for item in self.reddit.inbox.all(limit=1000):
			if item.new: continue
			if item.author != 'chaintip': continue
			if isinstance(item, praw.models.Message) and item.subject == 'Trying to tip yourself?': 
				continue
			if Reddit.p_mark_1.match(item.body): 
				continue
			if Reddit.p_mark_2.match(item.body): 
				continue

			if item.author == 'chaintip' and item.fullname not in self.items_by_fullname:
				limit -= 1
				items.append(item)

			if limit <= 0:
				break

		self.print_error("found ", len(items), "new items")
		self.reddit.inbox.mark_unread(items)
		self.items_by_fullname = {} # to enable unread() loop to read everything

	def markPaidTipsRead(self):
		if not read_config(self.wallet_ui.wallet, "mark_read_paid_tips"):
			return

		if hasattr(self.wallet_ui, "tiplist"):
			tips = [tip for tip in self.wallet_ui.tiplist.tips.values() \
				if tip.read_status == 'new' 
				and tip.isPaid()
			]
			if len(tips) > 0:
				self.print_error("marking {len(tips)} new paid tips as read")
				self.mark_read_tips(tips, include_associated_items=True)

	def markReadFinishedTips(self):
		if not read_config(self.wallet_ui.wallet, "mark_read_confirmed_tips"):
			return

		if hasattr(self.wallet_ui, "tiplist"):
			tips = [tip for tip in self.wallet_ui.tiplist.tips.values() if tip.read_status == "new" and tip.isFinished()]
			if len(tips) > 0:
				self.print_error(f"marking {len(tips)} finished tips as read")
				self.mark_read_tips(tips, include_associated_items=True)


	def mark_read_tips(self, tips, include_associated_items=True, unread=False):
		"""call mark_read() on messages associated with the given 'tips' 
		and remove the tips from tiplist"""
		tips_with_messages = [tip for tip in tips if tip.chaintip_message and isinstance(tip, RedditTip)]
		items = [tip.chaintip_message for tip in tips_with_messages]
		if include_associated_items:
			items += [tip.claim_or_returned_message for tip in tips_with_messages if hasattr(tip, "claim_or_returned_message")]
			items += [tip.chaintip_confirmation_comment for tip in tips_with_messages if hasattr(tip, "chaintip_confirmation_comment")]
		self.print_error(f"will mark_read() {len(items)} items (associated from {len(tips_with_messages)} tips).")
		self.mark_read_items(items, unread)

	def mark_read_items(self, items: list, unread: bool = False):
		if unread:
			self.reddit.inbox.mark_unread(items)
		else:
			self.reddit.inbox.mark_read(items)

		for item in items:
			if isinstance(item, praw.models.Message):
				tip = self.tip_or_message_by_message[item.id]
				if isinstance(tip, RedditTip):
					tip.read_status = 'read' if not unread else 'new'
					self.wallet_ui.tiplist.updateTip(tip)

	def mark_read_unassociated_items(self):
		# mark_read all unassociated items
		items = \
			[o["comment"] for o in self.unassociated_chaintip_comments_by_tipping_comment_id.values()]
		for l in self.unassociated_claim_return_by_tipping_comment_id.values():
			items += [o["message"] for o in l]
		self.print_error("unassociated items: ", items)
		self.mark_read_items(items)
		self.unassociated_claim_return_by_tipping_comment_id = defaultdict(list)
		self.unassociated_chaintip_comments_by_tipping_comment_id = {}

	def findTipByReference(self, reference):
		for tip in self.wallet_ui.tiplist.tips.values():
			if tip.getReference() == reference:
				return tip
		raise Exception(f"tip not found by reference {reference}")

	p_claimed_subject = re.compile('Tip claimed.')
	p_returned_subject = re.compile('Tip returned to you.')
	p_funded_subject = re.compile('Tip funded.')
	p_claimed_or_returned_message = re.compile('Your \[tip\]\(.*_/(\S*)\) of (\d*\.\d*) Bitcoin Cash.*to u/(\S*).* has \[been (\S*)\].*', re.MULTILINE | re.DOTALL)
	p_various_messages = re.compile('Your tip to u/(\S*) for their \[(.*)\]\(.*/(\w*)/(\w*)/\).*of (\d*\.\d*) Bitcoin Cash.*has \[been (\S*)\].*', re.MULTILINE | re.DOTALL)
	def parseClaimedOrReturnedMessage(self, message: praw.models.Message):
		#print_error("checking if message is claim/returned, subject", message.subject)

		# claimed message
		if not self.p_claimed_subject.match(message.subject) \
			and not self.p_returned_subject.match(message.subject) \
			and not self.p_funded_subject.match(message.subject) \
		:
			return False

		parsed_ok = False
		tipping_comment_id = None
		reference = None # can be tipping_comment id or tippee_post_id or tippee_comment_id
		post_or_comment = None # initialize for debugging output below

		#print_error("detected claimed/returned message, body", message.body)
		m = self.p_claimed_or_returned_message.match(message.body)
		if m:
			confirmation_comment_id = m.group(1)
			tipping_comment_id = RedditTip.sanitizeID(self.reddit.comment(confirmation_comment_id).parent_id)
			reference = tipping_comment_id
			amount = m.group(2)
			claimant = m.group(3)
			action = m.group(4)
			parsed_ok = True
			# print_error("parsed claimed message", message.id)
			# print_error("   tipping_comment_id:", tipping_comment_id)
			# print_error("   amount: ", amount)
			# print_error("   claimant:", claimant)
			# print_error("   action:", action)
		else:
			m = self.p_various_messages.match(message.body)
			if m:
				#self.print_error("subject:", message.subject)
				#self.print_error("body: ", message.body)
				# print_error("   group 1", m.group(1))
				# print_error("   group 2", m.group(2))
				# print_error("   group 3", m.group(3))
				# print_error("   group 4", m.group(4))
				# print_error("   group 5", m.group(5))
				# print_error("   group 6", m.group(6))

				post_or_comment = m.group(2)
				if post_or_comment == 'post':
					reference = RedditTip.sanitizeID(m.group(3))
				elif post_or_comment == 'comment':
					reference = RedditTip.sanitizeID(m.group(4))
				else:
					confirmation_comment_id = m.group(4)
					tipping_comment_id = self.reddit.comment(confirmation_comment_id).parent_id
					reference = tipping_comment_id
				amount = m.group(5)
				claimant = m.group(1)
				action = m.group(6)
				parsed_ok = True

#		if "user4morethan2mins" in message.subject or "user4morethan2mins" in message.body:
		# if post_or_comment is None:
		# 	self.print_error("subject:", message.subject)
		# 	self.print_error("body: ", message.body)
		# 	print_error("   reference", reference)
		# 	print_error("   tipping_comment_id", tipping_comment_id)
		# 	print_error("   post_or_comment", post_or_comment)
		# 	print_error("   action", action)
		# 	print_error("   parsed ok", parsed_ok)

		if parsed_ok and reference is not None:
			#self.print_error("", message.fullname, ": looking for tip...")
			# find tip matching claim and set its acceptance_status
			try:
				tip = self.findTipByReference(reference)
				#self.print_error(f"when parsing claim/returned message {message.id}: found matching tip (for claim)", tip)
				self.print_error("", message.fullname, ": setAcceptance...()")
				tip.setAcceptanceOrConfirmationStatus(message, action)
			except: 
				self.unassociated_claim_return_by_tipping_comment_id[reference].append({
					"message": message,
					"action": action
				})
				#self.print_error(f"when parsing claim/returned message {message.id}: tip with reference {reference} not found. Not registering '{action}' status.")

			return True
		else:
			self.print_error("message", message.id, ": body not claim return: ", message.body)

		return False

#	p_confirmation_comment = re.compile('.*u/(\S*).*\[.*\]\(.*/(bitcoincash:\w*)\).*', re.MULTILINE | re.DOTALL)
	p_confirmation_comment_please_claim = re.compile('.*u/(\S*), you\'ve \[been sent\]\(.*/(bitcoincash:\w*)\).*Please \[claim it!\].*', re.MULTILINE | re.DOTALL)
	p_confirmation_comment = re.compile('.*u/(\S*), you\'ve \[been sent\]\(.*/(bitcoincash:\w*)\).*', re.MULTILINE | re.DOTALL)
	p_confirmation_comment_claimed = re.compile('.*u/(\S*).*has \[claimed\].*', re.MULTILINE | re.DOTALL)
	p_confirmation_comment_returned = re.compile('.*\[chaintip\].* has \[returned\]\(.*/(bitcoincash:\w*)\).*', re.MULTILINE | re.DOTALL)
	def parseChaintipComment(self, comment: praw.models.Comment):
			tipping_comment_id = RedditTip.sanitizeID(comment.parent_id)
			tip = self.wallet_ui.tiplist.tips.get(tipping_comment_id, None)

			status = None

			if Reddit.p_confirmation_comment.match(comment.body):
				status = 'confirmed'

			if Reddit.p_confirmation_comment_please_claim.match(comment.body):
				status = 'unclaimed'

			if Reddit.p_confirmation_comment_claimed.match(comment.body):
				status = 'claimed'

			if Reddit.p_confirmation_comment_returned.match(comment.body):
				status = 'returned'

			# if comment.id == "gyb1ayx":
			# 	self.print_error("gyb1ayx body", comment.body)
			# 	self.print_error("gyb1ayx parsed as", status)

			# set data on tip (or defer)
			if status:
				if tip:
					tip.chaintip_confirmation_status = status
					tip.chaintip_confirmation_comment = comment
					tip.update()
				else:
					self.unassociated_chaintip_comments_by_tipping_comment_id[tipping_comment_id] = {
						"comment": comment,
						"status": status
					}
			else:
				self.print_error("chaintip comment doesn't parse: ", comment.body)

	def digestItem(self, item, item_is_new=False):
		# digest message
		if isinstance(item, praw.models.Message):
			self.digestMessage(item, item_is_new=True)

		# digest comment
		elif isinstance(item, praw.models.Comment):
			self.parseChaintipComment(item)

	def digestMessage(self, item, item_is_new=False):
		if item is None:
			return
		#self.print_error("incoming item of type", type(item))

		if isinstance(item, praw.models.Message):
			message = item
			# if message hasn't been seen before, digest according to its nature
			if message.id not in self.tip_or_message_by_message: 
				self.tip_or_message_by_message[message.id] = message
				claimed_or_returned = self.parseClaimedOrReturnedMessage(message)

				if not claimed_or_returned: # must be a tip message
					tip = RedditTip(self.wallet_ui.tiplist, self)
					tip.parseChaintipMessage(message)
					self.tip_or_message_by_message[message.id] = tip
					if item_is_new:
						tip.read_status = 'new'
					if tip.isValid():
						if not self.should_quit:
							self.new_tip.emit(tip)

			# if we've seen the message before, just mark associated tip as "new"
			elif item_is_new:
				tip = self.tip_or_message_by_message[message.id]
				if isinstance(tip, RedditTip):
					tip.read_status = 'new'
					self.wallet_ui.tiplist.updateTip(tip)

	def fetchTippingComments(self):
		if hasattr(self.wallet_ui, "tiplist"):
			tips = self.wallet_ui.tiplist.tips.values()

			# construct list of tips to work on
			tips_without_tipping_comments = list([tip for tip in tips if hasattr(tip, "tipping_comment_id") and tip.tipping_comment_id is not None and (not hasattr(tip, "tipping_comment") or tip.tipping_comment is None)])
			# prefer unpaid tips which we NEED to get the tipping coments for
			tips_without_tipping_comments.sort(key=lambda t: t.isPaid()) 

			# get a batch of comments
			tipping_comment_ids = [tip.tipping_comment_id for tip in tips_without_tipping_comments[:11]]
			if len(tipping_comment_ids) > 0:
				self.print_error(f"fetchTippingComments(): reddit.info({tipping_comment_ids})")
				for info in self.reddit.info(fullnames = tipping_comment_ids):
					if self.should_quit:
						break
					#self.print_error("info", info)
					try:
						tip = self.findTipByReference(info.fullname)
						tip.parseTippingComment(info)
					except Exception as e: # possibly tip was removed while we made the request
						self.print_error(f"fetchTippingComments() error: {e}")


	def run(self):
		self.print_error("Reddit.run() called")
		tips = []

		self.await_reddit_authorization()

		#self.markChaintipMessagesUnread(1000)

		max_age_days = 3
		do_read_from_read = False

		# use inbox.unread(), not inbox.stream
		cycle = 0
		while not self.should_quit:
			counter = 0
			try:
				items_this_cycle = 0
				for item in self.reddit.inbox.unread(limit=None):

					# break early in case of shutdown
					if self.should_quit:
						break

					# break on first already-digested message
					if item.fullname in self.items_by_fullname.keys():
						#self.print_error("aborting loading items at already-loaded item", item.fullname)
						break
					self.items_by_fullname[item.fullname] = item

					if item is not None:
						items_this_cycle += 1

					# only read chaintip-authored item
					if item.author != 'chaintip':
						continue

					counter += 1

					self.digestItem(item, item_is_new=True)

				if counter > 0:
					self.print_error(f"loaded {counter} items, sleeping...")
					counter = 0
				else:
					#self.print_error("no more unread messages to load, sleeping")
					cnt = 20
					while not self.should_quit and cnt > 0:
						sleep(0.1)
						cnt -= 1

				# some "background tasks"
				
				self.fetchTippingComments()

				#self.wallet_ui.print_debug_stats()

				self.markReadFinishedTips()
			
				self.refreshTips()
			
				self.transition_amount_set_2_ready_to_pay()
			
				if hasattr(self.wallet_ui, "autopay") and self.wallet_ui.autopay:
					self.wallet_ui.autopay.do_work()

				if False and items_this_cycle > 0:
					# print unassociated infos:
					for k, crl in self.unassociated_claim_return_by_tipping_comment_id.items():
						for cr in crl:
							item = cr["message"]
							self.print_error(f"{k}: {format_time(item.created_utc)} {item.subject}")

				self.wallet_ui.persistTipList()

				# after first cycle, assumption is that unassociated items are for old tips that will never load
				# note: this assumption is false with the "TEMPORARY load more items" feature
				if False and cycle == 0:
					self.mark_read_unassociated_items()
				cycle += 1
			except prawcore.exceptions.ServerError as e:
				self.print_error("Reddit ServerError", e, "retrying later...")
				sleep(30)

		# --- wind down ----

		self.mark_read_unassociated_items()

		self.print_error("exited reddit inbox streaming")

		self.dathread.quit()






#########################################################################################
#                                                                                       #
#    88888888ba                     88          88 88    888888888888 88                #
#    88      "8b                    88          88 ""   ,d    88      ""                #
#    88      ,8P                    88          88      88    88                        #
#    88aaaaaa8P' ,adPPYba,  ,adPPYb,88  ,adPPYb,88 88 MM88MMM 88      88 8b,dPPYba,     #
#    88""""88'  a8P_____88 a8"    `Y88 a8"    `Y88 88   88    88      88 88P'    "8a    #
#    88    `8b  8PP""""""" 8b       88 8b       88 88   88    88      88 88       d8    #
#    88     `8b "8b,   ,aa "8a,   ,d88 "8a,   ,d88 88   88,   88      88 88b,   ,a8"    #
#    88      `8b `"Ybbd8"'  `"8bbdP"Y8  `"8bbdP"Y8 88   "Y888 88      88 88`YbbdP"'     #
#                                                            f            88             #
#                                                                        88             #
#########################################################################################


class RedditTip(Tip):

	def sanitizeID(id):
		if id[0] == "t" and id[2] == "_":
			return id
		else:
			return "t1_" + id

	def __str__(self):
		return f"RedditTip {self.getID()}: {self.amount_bch} to {self.username}"

	def __init__(self, tiplist: TipList, reddit: Reddit):
		Tip.__init__(self, tiplist)
		self.platform = "reddit"
		self.reddit = reddit
		self.acceptance_status = ""
		self.read_status = "read" # will be set to "new" by inbox streamer

		self.chaintip_message_id = ""
		self.chaintip_message_created_utc = ""
		self.chaintip_message_author_name = ""
		self.chaintip_message_subject = ""

	# Tip overrides

	def from_dict(self, d: dict):
		"""used to load from wallet storage"""
		self.tipping_comment_id = d["tipping_comment_id"]
		self.tippee_comment_id = d["tippee_comment_id"]
		self.tippee_post_id = d["tippee_post_id"]
		self.read_status = d["read_status"]
		self.chaintip_message_id = d["chaintip_message_id"]
		self.chaintip_message_created_utc = d["chaintip_message_created_utc"]
		self.chaintip_message_subject = d["chaintip_message_subject"]
		self.chaintip_message_author_name = d["chaintip_message_author_name"]

	def to_dict(self):
		return {
			"tipping_comment_id": self.tipping_comment_id,
			"tippee_comment_id": self.tippee_comment_id,
			"tippee_post_id": self.tippee_post_id,
			"read_status": self.read_status,
			"chaintip_message_id": self.chaintip_message_id,
			"chaintip_message_created_utc": self.chaintip_message_created_utc,
			"chaintip_message_subject": self.chaintip_message_subject,
			"chaintip_message_author_name": self.chaintip_message_author_name,
		}

	def getID(self):
		return self.chaintip_message_id

	def getReference(self):
		if self.tipping_comment_id:
			return self.tipping_comment_id
		elif self.tippee_comment_id:
			return self.tippee_comment_id
		elif self.tippee_post_id:
			return self.tippee_post_id
		else:
			return RedditTip.sanitizeID(self.chaintip_message.fullname)

	def refreshAmount(self):
		if not self.isPaid():
			self.print_error("refresh being called and activates on tip: ", self)
			self.parseChaintipMessage()
			# re-parse tipping comment to re-set amount
			if hasattr(self, "tipping_comment") and self.tipping_comment:
				self.parseTippingComment(self.tipping_comment)
			else:
				if hasattr(self, "tipping_comment_id") and self.tipping_comment_id:
					self.fetchTippingComment()
				else:
					self.setAmount()
		self.update()

	#

	def isValid(self):
		 return \
			self.is_chaintip and \
			self.chaintip_message and \
			self.chaintip_message.author == 'chaintip' and \
			self.type == 'send' 

	def isPaid(self):
		if not self.payment_status: return False
		return self.payment_status[:4] == "paid"

	def isFinished(self):
		return self.isPaid() \
			and hasattr(self, "acceptance_status") and ( \
				(self.acceptance_status == "claimed") or \
				(self.acceptance_status == "returned") or \
				(self.acceptance_status == "received") or \
				(self.acceptance_status == "linked" and hasattr(self, "chaintip_confirmation_status") and self.chaintip_confirmation_status == "confirmed") or \
				(self.acceptance_status == "not yet linked" and hasattr(self, "chaintip_confirmation_status") and self.chaintip_confirmation_status == "returned") \
			)

	p_subject_outgoing_tip = re.compile('Tip (\S*)')
	p_tip_comment = re.compile('.*\[your tip\]\(\S*/_/(\S*)\).*', re.MULTILINE | re.DOTALL)
	p_recipient_acceptance = re.compile('^u/(\S*) has (.*linked).*Bitcoin Cash \(BCH\) to: \*\*(bitcoincash:q\w*)\*\*.*', re.MULTILINE | re.DOTALL)
	p_sender = re.compile('^u/(\S*) has just sent you (\S*) Bitcoin Cash \(about \S* USD\) \[via\]\(\S*/_/(\S*)\) .*', re.MULTILINE | re.DOTALL)
	p_stealth = re.compile('.*Tip \*\*.*\*\* for their \[(\w*)\]\((/(r/\w*)/\S*/(\w*)/(\w*)/)\).*', re.MULTILINE | re.DOTALL)

	def parseChaintipMessage(self, message: praw.models.Message):
		self.chaintip_message = message
		self.is_chaintip = False
		self.type = None
		self.default_amount_used = False
		self.tippee_comment_id = None
		self.tippee_post_id = None
		self.tippee_content_link = None

		message = self.chaintip_message

		self.id = message.id
		self.subject = message.subject



		# parse chaintip message
		reference = None
		if hasattr(self.chaintip_message.author, "name") and self.chaintip_message.author.name == 'chaintip':
			#self.print_error("--- parsing chaintip message, subject:", self.subject, "---")
			self.is_chaintip = True
			#self.print_error(f"parsing chaintip message {message.id}")
			#self.print_error(self.chaintip_message.body)

			# "Tip funded."
			if self.chaintip_message.subject == "Tip funded.":
				self.print_error("IMPLEMENT digesting 'Tip funded.' message, example message at hand:", self.chaintip_message.id)
				return

			# "Tip claimed." <- we need to ignore this here, p_tip_comment will catch it as tip otherwise
			if self.chaintip_message.subject == "Tip claimed.":
				return

			# "You've been tipped!"
			elif self.chaintip_message.subject == "You've been tipped!":
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
			elif RedditTip.p_subject_outgoing_tip.match(self.chaintip_message.subject):
				self.type = 'send'
				self.direction = 'outgoing'

				# match "your tip"
				m = RedditTip.p_tip_comment.match(self.chaintip_message.body)
				if m:
					self.tipping_comment_id = RedditTip.sanitizeID(m.group(1))
					reference = self.tipping_comment_id

				# match ... has (not) linked ... Bitcoin Cash (BCH) to <address>
				m = RedditTip.p_recipient_acceptance.match(self.chaintip_message.body)
				if m:
					self.username = m.group(1)
					if m.group(2) == "not yet linked":
						self.acceptance_status = 'not yet linked'
					else:
						self.acceptance_status = 'linked'
					self.recipient_address = Address.from_cashaddr_string(m.group(3))

				# stealth: match "for their <post|comment> (...)"
				m = RedditTip.p_stealth.match(self.chaintip_message.body)
				if m:
					self.setAmount()
					self.chaintip_confirmation_status = '<stealth>'
					post_or_comment = m.group(1)
					self.subreddit_str = m.group(3)
					self.tippee_content_link = m.group(2)
					if post_or_comment == 'comment': 	
						self.tippee_comment_id = RedditTip.sanitizeID(m.group(5))
						reference = self.tippee_comment_id
					if post_or_comment == 'post':
						self.tippee_post_id = RedditTip.sanitizeID(m.group(4))
						reference = self.tippee_post_id
						#self.print_error("reference is tippee_post_id", reference)
					# self.print_error("   m.group(1)", m.group(1))
					# self.print_error("   m.group(2)", m.group(2))
					# self.print_error("   m.group(3)", m.group(3))
					# self.print_error("   m.group(4)", m.group(4))
					# self.print_error("   m.group(5)", m.group(5))

			if reference:
				# associate possible already-parsed claim/return message
				claim_return_list = self.reddit.unassociated_claim_return_by_tipping_comment_id[reference]
				if len(claim_return_list) > 0:
					for claim_return in claim_return_list:
						self.setAcceptanceOrConfirmationStatus(claim_return["message"], claim_return["action"])

				# associate possible confirmation comment
				confirmation = self.reddit.unassociated_chaintip_comments_by_tipping_comment_id.pop(self.tipping_comment_id, None)
				if confirmation:
					self.chaintip_confirmation_status = confirmation["status"]
					self.chaintip_confirmation_comment = confirmation["comment"]

			# copy values to top level
			self.chaintip_message_id = self.chaintip_message.id
			self.chaintip_message_created_utc = self.chaintip_message.created_utc
			self.chaintip_message_author_name = self.chaintip_message.author.name
			self.chaintip_message_subject = self.chaintip_message.subject

	def setAcceptanceOrConfirmationStatus(self, claim_or_returned_message, action):
		if self.acceptance_status in ("received", "claimed", "returned"):
			self.update()
			return
		if self.isFinished():
			self.update()
			return
		self.acceptance_status = action
		self.claim_or_returned_message = claim_or_returned_message
		self.update()


	def fetchTippingComment(self):
		# fetch tipping comment
		if self.tipping_comment_id and (not hasattr(self, "tipping_comment") or not self.tipping_comment):
			self.tipping_comment = self.reddit.reddit.comment(id = self.tipping_comment_id[3:])
			self.parseTippingComment(self.tipping_comment)
			self.update()


	p_tip_amount_unit = re.compile('.*u/chaintip ((\S*)\s*(\S*))', re.MULTILINE | re.DOTALL)
	p_tip_prefix_symbol_decimal = re.compile('.*u/chaintip (.) ?(\d+\.?\d*).*', re.MULTILINE | re.DOTALL)
	def parseTippingComment(self, comment):
		#self.print_error("got tipping comment:", comment.body)
		self.tipping_comment = comment

		# set tippee_coment_id and tippee_content_link
		if not self.tippee_comment_id:
			self.tippee_comment_id = self.tipping_comment.parent().id
		self.tippee_content_link = self.tipping_comment.parent().permalink

		self.subreddit_str = "r/" + self.tipping_comment.subreddit.display_name
		self.tip_unit = ''

		if not self.isPaid():
			# match u/chaintip <prefix_symbol> <decimal>
			m = RedditTip.p_tip_prefix_symbol_decimal.match(self.tipping_comment.body)
			if m:
				try:
					prefix_symbol = m.group(1)
					amount = m.group(2)
					#self.print_error("parsed <prefix_symbox><decimal>: ", prefix_symbol, amount)
					self.tip_quantity = Decimal(amount)
					self.tip_unit = amount_config["prefix_symbols"][prefix_symbol]
					self.evaluateAmount()
				except Exception as e:
					self.print_error("Error parsing tip amount <prefix_symbol><decimal>: ", repr(e))
					#traceback.print_exc()

			# match u/chaintip <amount> <unit>
			if self.tip_unit == '':
				m = RedditTip.p_tip_amount_unit.match(self.tipping_comment.body)
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
						self.print_error("Error parsing tip amount <amount> <unit>: ", repr(e))
						#traceback.print_exc()
						self.setAmount()
				else: # use default amount
						self.setAmount()

	def setAmount(self, amount_bch: Decimal = None): 
		"""
			sets amount_bch and payment_status = 'amount set'
			if amount_bch==None: use default amount
		"""
		if amount_bch:
			self.default_amount_used = False
			self.amount_bch = amount_bch
		else:
			self.default_amount_used = True
			self.amount_bch = self.getDefaultAmountBCH()
		if not self.isPaid():
			self.payment_status = 'amount set'
			self.amount_set_time = time()
		self.update()

	def evaluateAmount(self):
		# find unit from amount config
		matching_units = (unit for unit in amount_config["units"] if self.tip_unit in unit["names"])
		unit = next(matching_units, None)
		if unit:
			rate = self.getRate(unit["value_currency"])
			amount_bch = round(self.tip_quantity * unit["value"] / rate, 8)
			self.setAmount(amount_bch = amount_bch)
			#self.print_error("found unit", unit, "value", unit["value"], "quantity", self.tip_quantity, "rate", rate)
		else:		
			# try tip_unit as currency 
			rate = self.getRate(self.tip_unit)
			amount_bch = round(self.tip_quantity / rate, 8)
			#self.print_error("rate for tip_unit", self.tip_unit, ": ", rate)
			self.setAmount(amount_bch = amount_bch)
			
	def getDefaultAmountBCH(self):
		wallet = self.reddit.wallet_ui.wallet
		(amount_key, currency_key) = ("default_amount", "default_amount_currency")
		if read_config(wallet, "use_linked_amount") and (self.acceptance_status == "linked" or self.acceptance_status == "claimed"):
			(amount_key, currency_key) = ("default_linked_amount", "default_linked_amount_currency")
		amount = Decimal(read_config(wallet, amount_key))
		currency = read_config(wallet, currency_key)
		try:
			rate = self.getRate(currency)
			amount_bch = round(amount / rate, 8)
			return amount_bch
		except Exception as e:
			self.print_error("error fetching rate:", e)
			return None

	def getRate(self, ccy: str):
		ccy = ccy.upper()
		if ccy == 'BCH':
			rate = Decimal("1.0")
		else:
			exchanges_by_ccy = get_exchanges_by_ccy(False)
			exchanges = exchanges_by_ccy[ccy]
			fx = self.reddit.wallet_ui.window.fx
			if type(fx.exchange).__name__ in exchanges:
				exchange = fx.exchange
			else:
				exchange_name = exchanges[0]
				klass = globals()[exchange_name]
				exchange = klass(None, None)
			rate = exchange.get_rates(ccy)[ccy]
		return rate


