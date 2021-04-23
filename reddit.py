from electroncash.util import PrintError, print_error, age, Weak, InvalidPassword
from electroncash.address import Address
from electroncash.exchange_rate import *
from decimal import Decimal
import datetime
import traceback
import re
from . import praw
from .praw.models import Comment, Message
from PyQt5.QtCore import QObject, pyqtSignal

from .model import Tip, TipList
from .config import c, amount_config

# praw setup
reddit = praw.Reddit(
		client_id=c["reddit"]["client_id"],
		client_secret=c["reddit"]["client_secret"],
		user_agent="unix:electroncash.chaintipper:v0.1a (by u/moleccc)",
		username=c["reddit"]["username"],
		password=c["reddit"]["password"],
)

class RedditTip(PrintError, Tip):

	p_subject = re.compile('Tip (\S*)')
	p_tip_comment = re.compile('.*\[your tip\]\(\S*/_/(\S*)\).*', re.MULTILINE | re.DOTALL)
	p_recipient = re.compile('^u/(\S*) has.*\*\*(bitcoincash:qrelay\w*)\*\*.*', re.MULTILINE | re.DOTALL)
	p_sender = re.compile('^u/(\S*) has just sent you (\S*) Bitcoin Cash \(about \S* USD\) \[via\]\(\S*/_/(\S*)\) .*', re.MULTILINE | re.DOTALL)

	def __init__(self, message: Message):
		Tip.__init__(self)
		self.platform = "reddit"
		# self.print_error(f"new RedditTip, created_utc: {message.created_utc}")

		self.chaintip_message = message
		self.id = message.id
		self.subject = message.subject
		self.is_chaintip = False
		self.type = None

		self.parseChaintipMessage(message)

	def isValid(self):
		 return \
		 	self.is_chaintip and \
		 	self.chaintip_message and \
		 	self.chaintip_message.author == 'chaintip' and \
		 	self.type == 'send' 

	def parseChaintipMessage(self, message):
		self.status = "parsing chaintip message"

		# parse chaintip message
		if self.chaintip_message.author.name == 'chaintip':
			self.is_chaintip = True
			self.print_error(f"parsing chaintip message {message.id}")
			#self.print_error(self.chaintip_message.body)

			# receive tip message
			if self.chaintip_message.subject == "You've been tipped!":
				m = RedditTip.p_sender.match(self.chaintip_message.body)
				if m:
					self.type = 'receive'
					#self.tipping_comment_id = m.group(1)
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
				comment = reddit.comment(id = self.tipping_comment_id)
				self.parseTippingComment(comment)

	p_tip = re.compile('.*(/u/chaintip (\S*)\s*(\S*))', re.MULTILINE | re.DOTALL)
	def parseTippingComment(self, comment):
		self.status = "parsing tip comment"
		self.print_error("got tipping comment:", comment.body)
		self.tipping_comment = comment
		m = RedditTip.p_tip.match(self.tipping_comment.body)
		self.tip_unit = 'sat'
		if m:
			self.print_error("match 1,2,3", m.group(1), ",", m.group(2), ",", m.group(3))
			self.print_error("m.lastindex", m.lastindex)
			try:
				self.tip_amount_text = m.group(1)
				self.print_error("match, lastindex: ", m.lastindex)
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
				self.amount_bch = amount_config["default_amount_bch"]

	def evaluateAmount(self):
		# in case all else fails, use default amount
		self.payment_status = 'using default amount'
		self.amount_bch = amount_config["default_amount_bch"]

		# find unit from amount config
		matching_units = (unit for unit in amount_config["units"] if self.tip_unit in unit["names"])
		unit = next(matching_units, None)
		if unit:
			rate = self.getRate(unit["value_currency"])
			self.amount_bch = round(self.tip_quantity * unit["value"] / rate, 8)
			self.print_error("found unit", unit, "value", unit["value"], "quantity", self.tip_quantity, "rate", rate)
			self.payment_status = 'amount parsed'
		else:		
			# try tip_unit as currency 
			rate = self.getRate(self.tip_unit)
			self.amount_bch = round(self.tip_quantity / rate, 8)
			self.print_error("rate for tip_unit", self.tip_unit, ": ", rate)
			self.payment_status = 'amount parsed'
			
	def getRate(self, ccy: str):
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

class Reddit(PrintError, QObject):
	new_tip = pyqtSignal(Tip)

	def __init__(self, tiplist):
		QObject.__init__(self)
		self.tiplist = tiplist

	def run(self):
		self.print_error("Reddit.run() called")
		tips = []

		for item in reddit.inbox.stream(pause_after=0):
			if item is None:
				continue
			if isinstance(item, Message):
				tip = RedditTip(item)
				if tip.isValid():
					#self.tiplist.dispatchNewTip(tip)
					self.new_tip.emit(tip)
			if isinstance(item, Comment):
				continue
				# re-parse amount here
				#self.update_tip.emit(tip)
			else:
				self.print_error(f"Unknown type {type(item)} in unread")
		self.print_error("exited streaming")
