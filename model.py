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
		self.payment_status = None

	def getID(self):
		raise Exception("getID() not implemented by subclass")

class TipList(PrintError):
	def __init__(self):
		self.tip_listeners = []
		self.tips = {} # tip instances by tipping_comment id

	def registerTipListener(self, tip_listener):
		self.tip_listeners.append(tip_listener)

	def unregisterTipListnere(self, tip_listener):
		self.tip_listeners.remove(tip_listener)

	def addTip(self, tip):
		self.tips[tip.getID()] = tip
		for tip_listener in self.tip_listeners:
			tip_listener.tipAdded(tip)

	def removeTip(self, tip):
		del self.tips[tip.getID()]
		for tip_listener in self.tip_listeners:
			tip_listener.tipRemoved(tip)

	def updateTip(self, tip):
		for tip_listener in self.tip_listeners:
			tip_listener.tipUpdated(tip)

class TipListener():
	def tipAdded(self, tip):
		print_error("not implemented")

	def tipRemoved(self, tip):
		print_error("not implemented")

	def tipUpdated(self, tip):
		print_error("not implemented")


