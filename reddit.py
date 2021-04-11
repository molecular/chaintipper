from electroncash.util import PrintError, print_error, age, Weak, InvalidPassword

import traceback
import praw
from praw.models import Comment, Message
import re

from .model import Tip
from .config import c

# praw setup
reddit = praw.Reddit(
		client_id=c["reddit_client_id"],
		client_secret=c["reddit_client_secret"],
		password=c["reddit_password"],
		user_agent=c["reddit_user_agent"],
		username=c["reddit_username"],
)

class RedditTip(PrintError, Tip):

	p_tip_comment = re.compile('.*\[your tip\]\(\S*/_/(\S*)\).*', re.MULTILINE | re.DOTALL)
	p_recipient = re.compile('^u/(\S*) has.*\*\*(bitcoincash:qrelay\w*)\*\*.*', re.MULTILINE | re.DOTALL)

	def __init__(self, message):
		Tip.__init__(self)
		self.platform = "reddit"
		# self.print_error(f"new RedditTip, created_utc: {message.created_utc}")
		self.chaintip_message = message
		self.id = message.id

		# parse chaintip message
		self.print_error(f"parsing chaintip message {message.id}")
		self.print_error(self.chaintip_message.body)
		m = RedditTip.p_tip_comment.match(self.chaintip_message.body)
		if m:
			self.tipping_comment_id = m.group(1)
		m = RedditTip.p_recipient.match(self.chaintip_message.body)
		if m:
			self.recipient_username = m.group(1)
			self.recipient_address = m.group(2)
		else:
			self.recipient_username = self.recipient_address = None
			self.print_error("p_recipient doesn't match")

class Reddit(PrintError):

	def __init__(self):
		self.print_error("I'm here")

	def sync(self):
		tips = []
		try:
			for item in reddit.inbox.unread():
				if isinstance(item, Message):
					tips.append(self.parseChaintipMessage(item))
					#item.mark_read()
				else:
					self.print_error(f"Unknown type {type(item)} in unread")
		except Exception:
				self.print_error("Fatal error in process_unread")
				self.print_error(traceback.format_exc())
		return tips

	def parseChaintipMessage(self, message):
		tip = RedditTip(message)
		return tip
