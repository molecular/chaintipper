from electroncash.util import PrintError, print_error, age, Weak, InvalidPassword
from electroncash.address import Address

from decimal import Decimal
import datetime
import traceback
import praw
from praw.models import Comment, Message
import re

import asyncio

from .model import Tip, TipList
from .config import c, amount_config

print_error("c", c)
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

	def __init__(self, message):
		Tip.__init__(self)
		self.platform = "reddit"
		# self.print_error(f"new RedditTip, created_utc: {message.created_utc}")

		self.chaintip_message = message
		self.id = message.id
		self.subject = message.subject
		self.is_chaintip = False

		self.parseChaintipMessage(message)

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

	p_tip = re.compile('^/u/chaintip (\S*) *(\S*) *(.*)')
	def parseTippingComment(self, comment):
		self.status = "parsing tip comment"
		self.print_error("got tipping comment:", comment.body)
		self.tipping_comment = comment
		m = RedditTip.p_tip.match(self.tipping_comment.body)
		self.tip_unit = 'sat'
		if m:
			try:
				self.tip_amount_text = m.group(0)
				self.print_error("match, lastindex: ", m.lastindex)
				if not m.group(2): # <tip_unit>
					self.tip_unit = m.group(1)
					self.tip_quantity = Decimal("1")
				elif m.lastindex >= 2: # <tip_quantity> <tip_unit>
					self.print_error("tip_q:", m.group(1))
					try:
						self.tip_quantity = amount_config["quantity_aliases"][m.group(1)]
					except Exception as e:
						self.tip_quantity = Decimal(m.group(1))
					self.tip_unit = m.group(2)
					# <onchain_message>
					if m.lastindex >= 3:
						self.tip_op_return = m.group(3)
				self.evaluateAmount()
			except Exception as e:
				self.print_error("Error parsing tip amount: ", repr(e))
				traceback.print_exc()
				self.amount_bch = amount_config["default_bch"]

	def evaluateAmount(self):
		matching_units = (unit for unit in amount_config["units"] if self.tip_unit in unit["names"])
		unit = next(matching_units, amount_config["units"][0])
		if unit:
			self.print_error("found unit", unit)
			if unit["value_currency"] == 'BCH':
				self.print_error("tip_quantity:", type(self.tip_quantity))
				self.amount_bch = self.tip_quantity * unit["value"]

class Reddit(PrintError):
	def __init__(self, tiplist):
		self.tiplist = tiplist

	def sync(self):
		self.print_error("Reddit.sync() called")
		tips = []
		subreddit = reddit.subreddit("learnpython")

		for item in reddit.inbox.stream(pause_after=0):
			if item is None:
				continue
			if isinstance(item, Message):
				tip = self.parseChaintipMessage(item)
				self.tiplist.dispatchNewTip(tip)
			else:
				self.print_error(f"Unknown type {type(item)} in unread")
		self.print_error("exited streaming")

	def parseChaintipMessage(self, message):
		tip = RedditTip(message)
		return tip
