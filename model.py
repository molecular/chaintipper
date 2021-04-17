from electroncash.util import PrintError, print_error

class Tip:
	def __init__(self):
		self.platform = 'unknown'

		# defaults
		self.status = "init"
		self.tipping_comment_id = None
		self.username = None
		self.recipient_address = None
		self.tipping_comment_id = None
		self.direction = None
		self.amount_bch = ""
		self.amount_bch = ""
		self.tip_amount_text = None
		self.tip_quantity = None
		self.tip_unit = None
		self.tip_op_return = None

class TipList():
	def __init__(self):
		self.tip_listeners = []

	def registerTipListener(self, tip_listener):
		self.tip_listeners.append(tip_listener)

	def unregisterTipListnere(self, tip_listener):
		self.tip_listeners.remove(tip_listener)

	def dispatchNewTip(self, tip):
		for tip_listener in self.tip_listeners:
			tip_listener.newTip(tip)

	def dispatchRemoveTip(self, tip):
		for tip_listener in self.tip_listeners:
			tip_listener.removeTip(tip)

class TipListener():
	def newTip(self, tip):
		print_error("not implemented")

	def removeTip(self, tip):
		print_error("not implemented")
