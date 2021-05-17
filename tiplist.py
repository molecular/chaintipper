import os
import queue
import random
import string
import tempfile
import threading
import time
import traceback
import sys

from enum import IntEnum
from decimal import Decimal
from time import sleep
from datetime import datetime

from PyQt5.QtGui import *
from PyQt5.QtCore import *
from PyQt5.QtWidgets import *

from electroncash.i18n import _
from electroncash_gui.qt import ElectrumWindow
from electroncash_gui.qt.util import webopen, MessageBoxMixin, MyTreeWidget
from electroncash.transaction import Transaction
from electroncash.util import PrintError, print_error, age, Weak, InvalidPassword, format_time, NotEnoughFunds
from electroncash import keystore, get_config
from electroncash.bitcoin import COIN, TYPE_ADDRESS
from electroncash.storage import WalletStorage
from electroncash.keystore import Hardware_KeyStore
from electroncash.wallet import Standard_Wallet, Multisig_Wallet
from electroncash.address import Address
from electroncash.wallet import Abstract_Wallet
import electroncash.web as web

from .model import Tip, TipList, TipListener
from .config import c
from .util import read_config, write_config

from .reddit import Reddit, RedditTip

class TipListItem(QTreeWidgetItem, PrintError):

	def __init__(self, o):
		if isinstance(o, list):
			QTreeWidgetItem.__init__(self, o)
		elif isinstance(o, Tip):
			self.tip = o
			self.tip.tiplist_item = self
			self.__init__(self.getDataArray(self.tip))
		else:
			QTreeWidgetItem.__init__(self)

	def getDataArray(self, tip):
		return [
			#tip.id,
			format_time(tip.chaintip_message.created_utc), 
			#tip.type,
			tip.read_status,
			tip.acceptance_status,
			tip.payment_status,
			"{0:.8f}".format(tip.amount_received_bch) if isinstance(tip.amount_received_bch, Decimal) else "",
			#str(tip.qualifiesForAutopay()),
			#tip.chaintip_message.author.name,
			#tip.chaintip_message.subject,
			tip.subreddit_str if hasattr(tip, "subreddit_str") else "",
			tip.username,
			#tip.direction,
			tip.tip_amount_text,
			"{0:.8f}".format(tip.amount_bch) if isinstance(tip.amount_bch, Decimal) else "",
			"{0:.2f}".format(tip.amount_fiat) if tip.amount_fiat else "<no rate>",
			#tip.recipient_address.to_ui_string() if tip.recipient_address else None,
			#str(tip.tip_quantity),
			#tip.tip_unit,
			#tip.tipping_comment_id,
			tip.tipping_comment.body.partition('\n')[0] if hasattr(tip, "tipping_comment") else "",
			#tip.tippee_content_link
		]

	def refreshData(self):
		data = self.getDataArray(self.tip)
		for idx, value in enumerate(data, start=0):
			self.setData(idx, Qt.DisplayRole, value)


class TipListWidget(PrintError, MyTreeWidget, TipListener):

	default_sort = MyTreeWidget.SortSpec(1, Qt.AscendingOrder)

	def refresh_headers(self):
		headers = [
			#_('ID'), 
			_('Date'),
			#_('Type'),
			_('Read'),
			_('Acceptance'),
			_('Payment'),
			_('Received (BCH)'),
			#_('will autopay'), 
			#_('Author'), 
			#_('Subject'), 
			_('Subreddit'), 
			_('Recipient'), 
			#_('Direction'), 
			_('Tip Amount Text'),
			_('Amount (BCH)'),
			"amount_fiat", 
			#_('Recipient Address'),
			#_('Tip Quantity'),
			#_('Tip Unit'),
			#_('Tip Comment'), 
			_('Tip Comment body'),
			#_('Tippee Content Link')
		]
		fx = self.window.fx
		
		# replace 'amount_fiat' header
		headers = [_('Amount ({ccy})').format(ccy=fx.ccy) if h=='amount_fiat' else h for h in headers]
		self.update_headers(headers)

	def __init__(self, window: ElectrumWindow, wallet: Abstract_Wallet, tiplist: TipList, reddit: Reddit):
		MyTreeWidget.__init__(self, window, self.create_menu, [], 10, [],  # headers, stretch_column, editable_columns
							deferred_updates=True, save_sort_settings=True)

		self.window = window
		self.wallet = wallet
		self.tiplist = None # will be set at end of __init__
		self.reddit = reddit

		self.refresh_headers()

		if self.reddit == None:
			raise Exception("no reddit")

		self.print_error("TipListWidget.__init__()")
		self.setSelectionMode(QAbstractItemView.ExtendedSelection)
		self.setSortingEnabled(True)
		self.setIndentation(0)


		if c["use_categories"]:
			self.outgoing_items = QTreeWidgetItem([_("outgoing")])
			self.addTopLevelItem(self.outgoing_items)
			self.incoming_items = QTreeWidgetItem([_("incoming")])
			self.addTopLevelItem(self.incoming_items)
			self.other_items = QTreeWidgetItem([_("other messages")])
			#self.addTopLevelItem(self.other_items)

		self.setTiplist(tiplist)

	def __del__(self):
		if self.tiplist:
			self.tiplist.unregistertipListener(self)

	def setTiplist(self, tiplist):
		if self.tiplist:
			self.tiplist.unregistertipListener(self)

		self.tiplist = tiplist
		self.tiplist.registerTipListener(self)
		self.tips_by_address = dict()

	def calculateFiatAmount(self, tip):
		# calc tip.amount_fiat
		d_t = datetime.utcfromtimestamp(tip.chaintip_message.created_utc)
		fx_rate = self.window.fx.history_rate(d_t)

		if fx_rate and tip.amount_bch:
			try:
				self.print_error("fx_rate", fx_rate, "tip amount", tip.amount_bch)
				tip.amount_fiat = fx_rate * tip.amount_bch
			except Exception as e:
				traceback.print_exc(file=sys.stderr)
		else:
			tip.amount_fiat = None

	# TipListener implementation

	def tipAdded(self, tip):
		if tip.recipient_address:
			self.tips_by_address[tip.recipient_address] = tip 

		self.calculateFiatAmount(tip)
		TipListItem(tip) 

		if c["use_categories"]:
			category_item = self.getCategoryItemForTip(tip)
			category_item.setExpanded(True)
			category_item.addChild(tip.tiplist_item)
		else:
			self.addTopLevelItem(tip.tiplist_item)

		self.checkPaymentStatus()
		self.pay([tip])


	def tipRemoved(self, tip):
		if tip.recipient_address:
			del self.tips_by_address[tip.recipient_address]
		if hasattr(tip, 'tiplist_item'):
			if c["use_categories"]:
				category_item = self.getCategoryItemForTip(tip)
				category_item.removeChild(tip.tiplist_item)
			else:
				self.takeTopLevelItem(self.indexOfTopLevelItem(tip.tiplist_item))
			del tip.tiplist_item
		else:
			self.print_error("no tiplist_item")

	def tipUpdated(self, tip):
		#self.print_error("tip updated: ", tip)
		if hasattr(tip, 'tiplist_item'):
			self.calculateFiatAmount(tip)
			tip.tiplist_item.refreshData()
			self.checkPaymentStatus()
			self.pay([tip])

	#

	def pay(self, tips: list):
		"""constructs and broadcasts transaction paying the given tips. No questions asked."""
		if not hasattr(self.window, "network"):
			return False

		if len(tips) <= 0:
			return False

		# (re)check wether tips qualify for autopay
		tips = [tip for tip in tips if tip.qualifiesForAutopay()]

		if len(tips) <= 0:
			return

		# label
		desc = "chaintip "
		desc_separator = ""
		for tip in tips:
			if tip.recipient_address and tip.amount_bch and isinstance(tip.recipient_address, Address) and isinstance(tip.amount_bch, Decimal):
				desc += f"{desc_separator}{tip.amount_bch} BCH to u/{tip.username} ({tip.chaintip_message.id})"
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

			status, msg = self.window.network.broadcast_transaction(tx)
			self.print_error("status: ", status, "msg: ", msg)

			if status: # success
				# set tx label for history
				self.wallet.set_label(tx.txid(), text=desc, save=True)

				# this is a half-baked workaround for utxo set not being up-to-date on next payment
				self.wallet.wait_until_synchronized() # should give some time
				sleep(3) # my god, where have I gone?
			else:
				for tip in tips:
					tip.payment_status = "autopay error: " + msg
					self.tiplist.updateTip(tip)

			return status

			#self.wallet.wait_until_synchronized()
			#self.wallet.add_transaction(tx.txid(), tx)
			#self.wallet.add_tx_to_history(tx.txid())
			#self.window.broadcast_transaction(tx, desc)

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


	def create_menu(self, position):
		"""creates context-menu for single or multiply selected items"""

		def doPay(tips: list):
			"""Start semi-automatic payment of a list of tips using the payto dialog"""
			self.print_error("paying tips: ", [t.id for t in tips])
			w = self.parent # main_window

			valid_tips = [tip for tip in tips if tip.recipient_address and tip.amount_bch and isinstance(tip.recipient_address, Address) and isinstance(tip.amount_bch, Decimal)]

			# calc description
			desc, desc_separator = ("chaintip ", "")
			for tip in valid_tips:
				desc += f"{desc_separator}{tip.amount_bch} BCH to u/{tip.username} ({tip.chaintip_message.id})"
				desc_separator = ", "

			# calc payto
			(payto, payto_separator) = ("", "")
			if len(valid_tips) > 1:
				for tip in valid_tips:
					payto += payto_separator + tip.recipient_address.to_string(Address.FMT_CASHADDR) + ', ' + str(tip.amount_bch)
					payto_separator = "\n"
			else:
				payto = valid_tips[0].recipient_address.to_string(Address.FMT_CASHADDR)
				w.amount_e.setText(str(valid_tips[0].amount_bch))

			self.print_error("  desc:", desc)
			self.print_error("  payto:", payto)
			w.payto_e.setText(payto)
			w.message_e.setText(desc)
			w.show_send_tab()

		def doAutoPay(tips: list):
			self.pay(tips)

		def doOpenBrowser(path):
			webopen(c["reddit"]["url_prefix"] + path)

		def doOpenBrowserToTipeeContent(tip: Tip):
			webopen(c["reddit"]["url_prefix"] + tip.chaintip_message.permalink)

		def doOpenBlockExplorerTX(txid: str):
			URL = web.BE_URL(self.config, 'tx', txid)
			webopen(URL)

		def doOpenBlockExplorerAddress(address: Address):
			URL = web.BE_URL(self.config, 'addr', address)
			webopen(URL)

		def doMarkRead(tips: list, include_claim_returned_messages: bool = False):
			self.reddit.mark_read_tips(tips, include_claim_returned_messages)

		col = self.currentColumn()
		column_title = self.headerItem().text(col)

		# put tips into array (single or multiple if selection)
		count_display_string = ""
		item = self.itemAt(position)
		if len(self.selectedItems()) == 1:
			tips = [item.tip]
		else:
			tips = [s.tip for s in self.selectedItems()]
			count_display_string = f" ({len(tips)})"

		new_tips = [t for t in tips if t.read_status == 'new']
		new_count_display_string = f" ({len(new_tips)})" if len(new_tips)>1 else "" 

		unpaid_tips = [t for t in tips if t.payment_status != 'paid' and t.amount_bch]
		unpaid_count_display_string = f" ({len(unpaid_tips)})" if len(unpaid_tips)>1 else "" 

		autopay_tips = [t for t in unpaid_tips if t.qualifiesForAutopay()]
		autopay_count_display_string = f" ({len(autopay_tips)})" if len(autopay_tips)>1 else "" 


		# create the context menu
		menu = QMenu()
		if len(new_tips) > 0:
			# mark_read
			menu.addAction(_("mark read{}").format(new_count_display_string), lambda: doMarkRead(new_tips, True))
			menu.addSeparator()

		if len(tips) == 1:
			tip = tips[0]

			if tip.chaintip_message:
				menu.addAction(_("open browser to chaintip message"), lambda: doOpenBrowser("/message/messages/" + tip.chaintip_message.id))

			# open browser...			
			if tip.tippee_content_link:
				menu.addAction(_("open browser to the content that made you tip"), lambda: doOpenBrowser(tip.tippee_content_link))
			if tip.tipping_comment_id:
				menu.addAction(_("open browser to tipping comment"), lambda: doOpenBrowser(tip.tipping_comment.permalink))
			
			# open blockexplorer...
			menu.addSeparator()
			payment_count = len(tip.payments_by_txhash)
			if payment_count == 1:
				menu.addAction(_("open blockexplorer to payment tx"), lambda: doOpenBlockExplorerTX(list(tip.payments_by_txhash.keys())[0]))
			elif payment_count > 1:
				for tx_hash, amount in tip.payments_by_txhash.items():
					menu.addAction(_("open blockexplorer to payment tx {tx_hash_short} ({amount} BCH)").format(tx_hash_short=tx_hash[:4]+"..."+tx_hash[-4:], amount=amount), lambda: doOpenBlockExplorerTX(tx_hash))
				menu.addSeparator()
			if hasattr(tip, "recipient_address") and tip.recipient_address:
				menu.addAction(_(f"open blockexplorer to recipient address"), lambda: doOpenBlockExplorerAddress(tip.recipient_address))

		menu.addSeparator()

		if len(unpaid_tips) > 0:
			menu.addAction(_(f"pay{unpaid_count_display_string}..."), lambda: doPay(unpaid_tips))
		if len(autopay_tips) > 0:
			menu.addAction(_(f"autopay{autopay_count_display_string}"), lambda: doAutoPay(autopay_tips))
		
		menu.exec_(self.viewport().mapToGlobal(position))

	# category items

	def getCategoryItemForTip(self, tip: Tip):
		"""Choose correct category (top level) item base on tip direction""" 
		i = self.other_items
		if tip.direction == 'incoming':
			i = self.incoming_items
		elif tip.direction == 'outgoing':
			i = self.outgoing_items
		return i

	def potentiallyAutoPay(self, tips: list):
		if read_config(self.wallet, "autopay", False):
			tips_to_pay = [tip for tip in tips if tip.payment_status == 'ready to pay']
			self.pay(tips_to_pay)

	def checkPaymentStatus(self):
		return 
		# txo = self.wallet.storage.get('txo', {})
		# self.txo = {tx_hash: self.wallet.to_Address_dict(value)
		# 	for tx_hash, value in txo.items()
		# 	# skip empty entries to save memory and disk space
		# 	if value}
		# for txhash in txo:
		# 	#self.print_error("  txhash", txhash)
		# 	##tx = Transaction.tx_cache_get(txhash)
		# 	tx = self.wallet.transactions.get(txhash)
		# 	#txinfo = self.wallet.get_tx_info(tx)
		# 	for txout in tx.outputs():
		# 		#self.print_error("     txout", txout)
		# 		#self.print_error("     address", txout[1])
		# 		address = txout[1]
		# 		satoshis = txout[2]

		# 		try:
		# 			tip = self.tips_by_address[address]
		# 			#self.print_error("   ****** TIP", tip, "paid in txhash", txhash)
		# 			tip.registerPayment(txhash, Decimal("0.00000001") * satoshis, "wallet")
		# 			# if tip.payment_status[:4] != "paid":
		# 			# 	tip.payment_status = "paid"
		# 			# 	tip.payment_txid = txhash
		# 			# 	self.tiplist.updateTip(tip)
		# 		except KeyError:
		# 			continue
		# 			#self.print_error("   cannot find tip for address", address)



			# hist = self.wallet.get_history(self.get_domain(), reverse=True)
			# for h in hist:
			# 	self.print_error("  h: ", h)


	# 	"""Returns the failure reason as a string on failure, or 'None'
	# 	on success."""
	# 	self.wallet.add_input_info(coin)
	# 	inputs = [coin]
	# 	self.print_error("recipient_address: ", recipient_address)
	# 	outputs = [(recipient_address.kind, recipient_address, coin['value'])]
	# 	kwargs = {}
	# 	if hasattr(self.wallet, 'is_schnorr_enabled'):
	# 		# This EC version has Schnorr, query the flag
	# 		kwargs['sign_schnorr'] = self.wallet.is_schnorr_enabled()
	# 	# create the tx once to get a fee from the size
	# 	tx = Transaction.from_io(inputs, outputs, locktime=self.wallet.get_local_height(), **kwargs)
	# 	fee = tx.estimated_size()
	# 	if coin['value'] - fee < self.wallet.dust_threshold():
	# 		self.print_error("Resulting output value is below dust threshold, aborting send_tx")
	# 		return _("Too small")
	# 	# create the tx again, this time with the real fee
	# 	outputs = [(recipient_address.kind, recipient_address, coin['value'] - fee)]
	# 	tx = Transaction.from_io(inputs, outputs, locktime=self.wallet.get_local_height(), **kwargs)
	# 	try:
	# 		self.wallet.sign_transaction(tx, self.password)
	# 	except InvalidPassword as e:
	# 		return str(e)
	# 	except Exception:
	# 		return _("Unspecified failure")
