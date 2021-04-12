from electroncash.util import PrintError, print_error, age, Weak, InvalidPassword

from decimal import Decimal
import datetime
import traceback
import praw
from praw.models import Comment, Message
import re

import asyncio

from .model import Tip
from .config import c

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

		# parse chaintip message
		if self.chaintip_message.author.name == 'chaintip':
			self.is_chaintip = True
			self.print_error(f"parsing chaintip message {message.id}")
			self.print_error(self.chaintip_message.body)

			# defaults
			self.tipping_comment_id = None
			self.username = None
			self.recipient_address = None
			
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
				self.amount_bch = Decimal("0.00001")
				m = RedditTip.p_tip_comment.match(self.chaintip_message.body)
				if m:
					self.tipping_comment_id = m.group(1)
					self.direction = 'outgoing'
				m = RedditTip.p_recipient.match(self.chaintip_message.body)
				if m:
					self.username = m.group(1)
					self.recipient_address = m.group(2)

class Reddit(PrintError):

	def __init__(self):
		self.tip_listeners = []

	def registerTipListener(self, tip_listener):
		self.tip_listeners.append(tip_listener)

	def unregisterTipListnere(self, tip_listener):
		self.tip_listeners.remove(tip_listener)

	def dispatchTip(self, tip):
		for tip_listener in self.tip_listeners:
			tip_listener.addTip(tip)

	def sync(self):
		self.print_error("Reddit.sync() called")
		tips = []
		subreddit = reddit.subreddit("learnpython")
		try:
			for submission in subreddit.hot(limit=10):
				print(submission.title)
		except Exception as e:
			print("error: ", repr(e))
			traceback.print_exc()

		for item in reddit.inbox.stream(pause_after=0):
			if item is None:
				continue
			if isinstance(item, Message):
				tip = self.parseChaintipMessage(item)
				self.dispatchTip(tip)
				#item.mark_read()
			else:
				self.print_error(f"Unknown type {type(item)} in unread")
		self.print_error("exited streaming")

	def parseChaintipMessage(self, message):
		tip = RedditTip(message)
		return tip

