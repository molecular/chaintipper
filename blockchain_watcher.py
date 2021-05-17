import traceback
from decimal import Decimal

from electroncash.util import PrintError
from electroncash.network import Network
from electroncash.address import Address
from electroncash.transaction import Transaction

from .model import TipListener

class BlockchainWatcher(TipListener, PrintError):
	"""
		BlockchainWatcher 
		listens for tips 
		and uses electrum network to watch for payments to recipient addresses 
		in order to mark tips as paid
	""" 

	def __init__(self, wallet, tiplist):
		self.wallet = wallet
		self.network = self.wallet.weak_window().network
		self.tiplist = tiplist
		self.tiplist.registerTipListener(self)
		self.hash2tip = {}
		self.requested_tx_hashes = {}
		self.tips_by_address = {}

	def __del__(self):
		self.tiplist.unregisterTipListener(self)		

	# stolen from synchronizer
	def parse_response(self, response):
		error = True
		try:
			if not response: return None, None, error
			error = response.get('error')
			return response['params'], response.get('result'), error
		finally:
			if error:
				self.print_error("response error:", response)

	def tipRemoved(self, tip):
		self.tips_by_address.pop(tip.recipient_address, None)

	def tipAdded(self, tip):
		self.tipUpdated(tip)

	def tipUpdated(self, tip):
		if isinstance(tip.recipient_address, Address):
			if tip.recipient_address not in self.tips_by_address:
				self.tips_by_address[tip.recipient_address] = tip

				scripthash = tip.recipient_address.to_scripthash_hex()
				if scripthash not in self.hash2tip.keys():
					self.hash2tip[scripthash] = tip

				# subscribe to scripthash
				#self.print_error("subscribing to scripthash", scripthash, "address:", tip.recipient_address)
				#self.print_error(f"now {len(self.hash2tip.keys())} scripthash subscriptions")
				if not self.network:
					self.print_error("no network, unable to check for tip payments")
				self.network.subscribe_to_scripthashes([scripthash], self.on_status_change)

				# get scripthash history
				#self.network.request_scripthash_history(scripthash, self.on_address_history)		

	def on_status_change(self, c):
		scripthash = c["params"][0]
		#txhash = c["result"]
		tip = self.hash2tip[scripthash]

		# get scripthash history
		self.network.request_scripthash_history(scripthash, self.on_address_history)		

	def on_address_history(self, response):
		params, result, error = self.parse_response(response)
		if error:
			return
		tx_hashes = map(lambda item: item['tx_hash'], result)
		self.request_tx(tx_hashes)
	

	def request_tx(self, tx_hashes):
		requests = []
		for tx_hash in tx_hashes:
			if tx_hash not in self.requested_tx_hashes.keys():
				self.requested_tx_hashes[tx_hash] = 17
				requests.append(('blockchain.transaction.get', [tx_hash]))
		#self.print_error("requesting transactions, requests: ", requests)
		self.network.send(requests, self.on_tx)

	def on_tx(self, response):
		#self.print_error("--- got tx response: ", response)
		params, result, error = self.parse_response(response)
		tx_hash = params[0] or ''
		if error:
			self.print_error("error for tx_hash {}, skipping".format(tx_hash))
			return
		try:
			tx = Transaction(result)
			for o in tx.outputs():
				#self.print_error("   output", o)
				address = o[1]
				satoshis = o[2]
				tip = self.tips_by_address.get(address, None)
				if tip:
					tip.registerPayment(tx_hash, Decimal("0.00000001") * satoshis, "chain")
				# else:
				# 	self.print_error("address", address, ": cannot find associated tip")
		except Exception:
			traceback.print_exc()
			self.print_msg("cannot deserialize transaction, skipping", tx_hash)
			return
		

