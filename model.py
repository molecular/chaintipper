from electroncash.util import PrintError, print_error
from decimal import Decimal
import weakref

class Tip(PrintError):
	def __init__(self, tiplist):
		self.tiplist_weakref = weakref.ref(tiplist)

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

		self.payments_by_txhash = {}
		self.amount_received_bch = None

	def getID(self):
		raise Exception("getID() not implemented by subclass")

	def update(self):
		if self.tiplist_weakref():
			self.tiplist_weakref().updateTip(self)

	def registerPayment(self, txhash: str, amount_bch: Decimal, source: str):
		#self.print_error(f"registerPayment({txhash}, {amount_bch})")
		if not txhash in self.payments_by_txhash.keys():
			self.payments_by_txhash[txhash] = amount_bch
			if not self.amount_received_bch:
				self.amount_received_bch = amount_bch
			else:
				self.amount_received_bch += amount_bch
			if len(self.payments_by_txhash) == 1:
				self.payment_status = "paid"
			else:
				self.payment_status = f'paid ({len(self.payments_by_txhash)} tx)'
			self.update()

class TipList(PrintError):
	def __init__(self):
		self.tip_listeners = []
		self.tips = {} # tip instances by tipping_comment id

	def debug_stats(self):
		return f"           Tiplist: {len(self.tips)} tips"

	def registerTipListener(self, tip_listener):
		self.tip_listeners.append(tip_listener)

	def unregisterTipListener(self, tip_listener):
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


