import traceback
from decimal import Decimal
from time import time

from electroncash import get_config
from electroncash.util import PrintError, NotEnoughFunds
from electroncash.network import Network
from electroncash.address import Address
from electroncash.transaction import Transaction
from electroncash.bitcoin import COIN, TYPE_ADDRESS

from .model import TipListener
from .util import read_config
from .config import c

class AutoPay(TipListener, PrintError):
	"""
		AutoPay 
		listens for tips matching autopay condition and pays them (in rate-throttled batches)
	""" 

	def __init__(self, wallet, tiplist):
		self.wallet = wallet
		self.network = self.wallet.weak_window().network
		self.tiplist = tiplist
		self.resetTimer()

		self.tips = []
		self.tiplist.registerTipListener(self)

	# def __del__(self):
	# 	self.tiplist.unregisterTipListener(self)		

	def resetTimer(self):
		self.last_payment_time = time()

	def debug_stats(self):

		return f"           AutoPay: {len(self.tips)} tips qualify for autopay\n\
                       {int(time() - self.last_payment_time)}s since last payment (or startup)"

	# TipListener overrides

	def tipRemoved(self, tip):
		True or False

	def tipAdded(self, tip):
		self.tipUpdated(tip)

	def tipUpdated(self, tip):
		if self.qualifiesForAutopay(tip):
			if not tip in self.tips:
				self.tips.append(tip)
		else:
			if tip in self.tips:
				self.tips.remove(tip)

	#

	def qualifiesForAutopay(self, tip):
		wallet = tip.reddit.wallet_ui.wallet

		# old?
		# if tip.isOld():
		# 	tip.payment_status = 'older than chaintipper'
		# 	return False

		# not ready to pay?
		if tip.payment_status != 'ready to pay': return False

		# recipient_address set?
		if \
			tip.recipient_address == None or \
			not isinstance(tip.recipient_address, Address) \
		:
			tip.payment_status = 'invalid recipient address'
			tip.update()
			return False

		# autopay deactivated?
		if not read_config(wallet, "autopay"): 
			tip.print_error("autopay: ", read_config(wallet, "autopay"))
			tip.payment_status = 'autopay disabled'
			tip.update()
			return False		

		# alread received something? (status should be 'paid' anyway, but to be sure...)
		if tip.amount_received_bch and tip.amount_received_bch > Decimal(0):
			return False

		# default amount disallowed?
		if read_config(wallet, "autopay_disallow_default") \
			and tip.default_amount_used \
		: 
			tip.payment_status = 'autopay disallowed (default amount)'
			tip.update()
			return False

		# amount limit exceeded?
		autopay_use_limit = read_config(wallet, "autopay_use_limit")
		autopay_limit_bch = Decimal(read_config(wallet, "autopay_limit_bch"))
		if autopay_use_limit and tip.amount_bch > autopay_limit_bch: 
			tip.payment_status = "autopay amount-limited"
			tip.update()
			return False

		return True

	def pay(self, tips: list):
		"""constructs and broadcasts transaction paying the given tips. No questions asked."""
		if not self.network:
			return False

		if len(tips) <= 0:
			return False

		# (re)check wether tips qualify for autopay
		tips = [tip for tip in tips if self.qualifiesForAutopay(tip)]

		if len(tips) <= 0:
			return

		# label
		desc = "chaintip "
		desc_separator = ""
		for tip in tips:
			if tip.recipient_address and tip.amount_bch and isinstance(tip.recipient_address, Address) and isinstance(tip.amount_bch, Decimal):
				desc += f"{desc_separator}{tip.amount_bch} BCH to u/{tip.username} ({tip.chaintip_message_id})"
				desc_separator = ", "
		self.print_error("label for tx: ", desc)

		# construct transaction
		outputs = []
		#outputs.append(OPReturn.output_for_stringdata(op_return))
		for tip in tips:
			address = tip.recipient_address
			amount = int(COIN * tip.amount_bch)
			outputs.append((TYPE_ADDRESS, address, amount))
			self.print_error("address: ", address, "amount:", amount)

		try:
			tx = self.wallet.mktx(outputs, password=None, config=get_config())

			self.print_error("txid:", tx.txid())
			self.print_error("tx:", tx)

			status, msg = self.network.broadcast_transaction(tx)
			self.print_error("status: ", status, "msg: ", msg)

			self.resetTimer()

			if status: # success
				# set tx label for history
				self.wallet.set_label(tx.txid(), text=desc, save=True)

				# this is a half-baked workaround for utxo set not being up-to-date on next payment
				#self.wallet.wait_until_synchronized() # should give some time
				#sleep(3) # my god, where have I gone?
			else:
				for tip in tips:
					tip.payment_status = "autopay error: " + msg
					self.tiplist.updateTip(tip)

			return status

		except Exception as e:
			self.print_error("error creating/sending tx: ", e)
			if isinstance(e, NotEnoughFunds):
				error = "not enough funds"
			else:
				error = "tx create/send error" #: " + str(e)
			for tip in tips:
				tip.payment_status = error
				self.tiplist.updateTip(tip)
			return False

	def do_work(self):
		"""should be called periodically"""
		# maybe replace by a thread instead of being driven in this way? 

		if time() - self.last_payment_time < c["autopay_min_wait_secs"]:
			return

		#autopay_tips = [tip for tip in self.tiplist.tips.values() if self.qualifiesForAutopay(tip)]
		self.pay(self.tips)
