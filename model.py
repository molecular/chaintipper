from electroncash.util import PrintError, print_error

import praw
from praw.models import Comment, Message

class Tip:

	def __init__(self):
		self.platform = 'unknown'
		