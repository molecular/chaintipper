import traceback
from decimal import Decimal
from time import time

from electroncash.util import PrintError
from electroncash.network import Network
from electroncash.address import Address
from electroncash.transaction import Transaction

from .model import TipListener

class StatisticsWallet(PrintError):
	counter = 0

	def __init__(self, follow_the_money, address):
		self.follow_the_money = follow_the_money
		self.address = address
		self.txs_by_hash = dict()
		self.tips = []
		self.requested_tx_hashes = {}

	def digest_tx(self, tx):
		# abort on too many txs
		if len(self.txs_by_hash.values()) > 42:
			for tip in self.tips:
				tip.recipient_usage = "too many txs (>42)"
				tip.update()
			return

		if tx.txid() not in self.txs_by_hash.keys():
			self.txs_by_hash[tx.txid()] = tx

			# update all the tips associated with the real recipicent address
			stats = self.render_stats()
			for tip in self.tips:
				if not hasattr(tip, "recipient_usage") or tip.recipient_usage != stats: 
					tip.recipient_usage = stats
					tip.update()

	def render_stats(self):
		# look at all txs collecting stats and info
		# balance_sats = 0
		# for tx in self.txs_by_hash.values():
		# 	# outputs
		# 	for o in tx.outputs():
		# 		address = o[1]
		# 		satoshis = o[2]
		# 		if address == self.address:
		# 			balance_sats += satoshis

		self.counter+=1
		if self.counter%100 == 0: self.print_error("counter=", self.counter)
		spend_state = 'hodl'
		for tx in self.txs_by_hash.values():
			# inputs
			for i in tx.inputs():
				if i["address"] == self.address:
					if len(tx.outputs()) > 1:
						spend_state = 'partial spend'
					elif len(tx.outputs()) == 1:
						spend_state = 'full spend'
					else:
						spend_state = f"<? {len(tx.outputs())} outputs>"
					count_vin = 1
					for i_other in tx.inputs():
						if i_other != i:
							count_vin += 1
							# found another input
							#self.print_error("----------- other input: ", i_other)
					if count_vin > 1:
							spend_state += f', {count_vin} vins'
					balance_sats = 0
					#self.print_error("   i", i)

		#balance = Decimal('0.00000001') * balance_sats
		stats = f"{spend_state}, {len(self.txs_by_hash.values())} txs"
		return stats

	def associateTip(self, tip):
		if not tip in self.tips:
			self.tips.append(tip)
			tip.recipient_usage = self.render_stats()
			#self.print_error("wallet", self.address.to_cashaddr(), "now has", len(self.tips), "tip(s) associated with it")

		# subscribe to recipient address scripthash
		if not self.follow_the_money.network:
			self.print_error("no network, unable to subscribe to real_recipient_address data")
		else:
			if not hasattr(self, 'scripthash'):
				self.scripthash = self.address.to_scripthash_hex()
				self.follow_the_money.network.subscribe_to_scripthashes([self.scripthash], self.on_status_change)

	def unassociateTip(self, tip):
		if tip in self.tips:
			self.tips.remove(tip)
		if len(tips) == 0 and hasattr(self, 'scripthash'):
			# unsubscribe
			self.follow_the_money.network.unsubscribe_from_scripthashes([self.scripthash])
			del self.scripthash

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

	def on_status_change(self, c):
		#self.print_error("follow_the_money on_status_change()")
		scripthash = c["params"][0]
		#txhash = c["result"]

		# get scripthash history
		self.follow_the_money.network.request_scripthash_history(scripthash, self.on_address_history)		

	def on_address_history(self, response):
		#self.print_error("follow_the_money on_address_history()")
		params, result, error = self.parse_response(response)
		if error:
			return

		#tx_hashes = map(lambda item: item['tx_hash'], result) this weirdly fails to deliver for some cases, replacing with procedural:
		tx_hashes = []
		for r in result:
			tx_hashes.append(r['tx_hash'])
		self.request_tx(tx_hashes)
	
	def request_tx(self, tx_hashes):
		requests = []
		for tx_hash in tx_hashes:
		# 	if tx_hash not in self.requested_tx_hashes.keys():
			self.requested_tx_hashes[tx_hash] = 17
			requests.append(('blockchain.transaction.get', [tx_hash]))
		self.follow_the_money.network.send(requests, self.on_tx)

	def on_tx(self, response):
		#self.print_error("--- got tx response: ", response)
		params, result, error = self.parse_response(response)
		#self.print_error("tx", params)
		tx_hash = params[0] or ''
		if error:
			self.print_error("error for tx_hash {}, skipping".format(tx_hash))
			return

		try:
			tx = Transaction(result)
			wallet = None

			# is tx TO self?
			for o in tx.outputs():
				address = o[1]
				satoshis = o[2]
				if address == self.address:
					wallet = self

			# is tx FROM self?
			for i in tx.inputs():
				if i["address"] == self.address:
					wallet = self

			# if either one, add tx to self
			if wallet:
				wallet.digest_tx(tx)

		except Exception:
			traceback.print_exc()
			self.print_msg("cannot deserialize transaction, skipping", tx_hash)
			return


	def __str__(self):
		return f"StatisticsWallet with {len(tx.values())} txs"


class FollowTheMoney(TipListener, PrintError):
	"""
		FollowTheMoney 
		listens for tips 
		and uses electrum network to follow the money to the users wallet 
		and categorize tips according to what the user does with the money
	""" 

	wallet_by_address = dict()
	def getStatisticsWalletForAddress(self, address):
		address_str = address.to_cashaddr()
		wallet = None
		if address_str in self.wallet_by_address:
			wallet = self.wallet_by_address[address_str]
		else:
			wallet = StatisticsWallet(self, address)
			self.wallet_by_address[address_str] = wallet
		return wallet

	def __init__(self, wallet, tiplist):
		self.wallet = wallet
		self.network = self.wallet.weak_window().network
		self.tiplist = tiplist

		self.tiplist.registerTipListener(self)

	def __del__(self):
		self.tiplist.unregisterTipListener(self)		

	def debug_stats(self):
		return f"    FollowTheMoney: {len(self.wallet_by_address)} statistics wallets"

	# TipListener overrides

	def tipRemoved(self, tip):
		pass

	def tipAdded(self, tip):
		self.tipUpdated(tip)

	def tipUpdated(self, tip):
		if hasattr(tip, "real_recipient_address") and isinstance(tip.real_recipient_address, Address):
			a_str = tip.real_recipient_address.to_cashaddr()
			#self.print_error("------ real recipient address", a_str)

			wallet = self.getStatisticsWalletForAddress(tip.real_recipient_address)
			wallet.associateTip(tip)

