import os
import queue
import random
import string
import tempfile
import threading
import time
from enum import IntEnum
from decimal import Decimal

from PyQt5.QtGui import *
from PyQt5.QtCore import *
from PyQt5.QtWidgets import *

from electroncash.i18n import _
from electroncash_gui.qt import ElectrumWindow
from electroncash_gui.qt.util import *
from electroncash.transaction import Transaction
from electroncash.util import PrintError, print_error, age, Weak, InvalidPassword, format_time
from electroncash import keystore, get_config
from electroncash.bitcoin import COIN, TYPE_ADDRESS
from electroncash.storage import WalletStorage
from electroncash.keystore import Hardware_KeyStore
from electroncash.wallet import Standard_Wallet, Multisig_Wallet
from electroncash.address import Address
from electroncash.wallet import Abstract_Wallet

from .model import Tip, TipList, TipListener
from .config import c
from .util import read_config, write_config

class TipListItem(QTreeWidgetItem):

	def __init__(self, o):
		if isinstance(o, list):
			QTreeWidgetItem.__init__(self, o)
		elif isinstance(o, Tip):
			self.tip = o
			self.tip.tiplist_item = self
			self.__init__([
				#o.id,
				format_time(o.chaintip_message.created_utc), 
				#o.type,
				o.payment_status,
				#o.chaintip_message.author.name,
				#o.chaintip_message.subject,
				o.username,
				#o.direction,
				str(o.amount_bch),
				#o.recipient_address.to_ui_string() if o.recipient_address else None,
				o.tip_amount_text,
				str(o.tip_quantity),
				o.tip_unit,
				#o.status
				#o.tipping_comment_id,
				o.tipping_comment.body.partition('\n')[0],
			])
		else:
			QTreeWidgetItem.__init__(self)

class TipListWidget(PrintError, MyTreeWidget, TipListener):

	default_sort = MyTreeWidget.SortSpec(1, Qt.AscendingOrder)

	def __init__(self, window: ElectrumWindow, wallet: Abstract_Wallet, tiplist: TipList):
		MyTreeWidget.__init__(self, window, self.create_menu, [
								#_('ID'), 
								_('Date'),
								#_('Type'),
								_('Payment Status'), 
								#_('Author'), 
								#_('Subject'), 
								_('Recipient'), 
								#_('Direction'), 
								_('Amount (BCH)'), 
								#_('Recipient Address'),
								_('Tip Amount Text'),
								_('Tip Quantity'),
								_('Tip Unit'),
								#_('Status'),
								#_('Tip Comment'), 
								_('Tip Comment body'),
							], 9, [],  # headers, stretch_column, editable_columns
							deferred_updates=True, save_sort_settings=True)

		self.window = window
		self.wallet = wallet
		self.tiplist = None

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

	def setTiplist(self, tiplist):
		if self.tiplist:
			self.tiplist.unregistertipListener(self)
			del self.tiplist

		self.tiplist = tiplist
		self.tiplist.registerTipListener(self)
		self.tips_by_address = dict()

	def pay(self, tips: list):
		"""constructs and broadcasts transaction paying the given tips. No questions asked."""
		if not hasattr(self.window, "network"):
			return False

		if len(tips) <= 0:
			return False

		# some sanity filtering just in case
		autopay_use_limit = read_config(self.wallet, "autopay_use_limit", c["default_autopay_use_limit"])
		autopay_limit_bch = Decimal(read_config(self.wallet, "autopay_limit_bch", c["default_autopay_limit_bch"]))
		tips = [tip for tip in tips if tip.payment_status == 'amount parsed' and (not autopay_use_limit or tip.amount_bch < autopay_limit_bch)]

		if len(tips) <= 0:
			return

		# label
		desc = "chaintip "
		desc_separator = ""
		for tip in tips:
			if tip.recipient_address and tip.amount_bch and isinstance(tip.recipient_address, Address) and isinstance(tip.amount_bch, Decimal):
				desc += f"{desc_separator}{tip.amount_bch} BCH to u/{tip.username} ({tip.chaintip_message.id})"
				desc_separator = ", "

		# construct transaction
		outputs = []
		#outputs.append(OPReturn.output_for_stringdata(op_return))
		for tip in tips:
			address = tip.recipient_address
			amount = int(COIN * tip.amount_bch)
			outputs.append((TYPE_ADDRESS, address, amount))
			self.print_error("address: ", address, "amount:", amount)
		tx = self.wallet.mktx(outputs, password=None, config=get_config())

		self.print_error("txid:", tx.txid())
		self.print_error("tx:", tx)

		# set tx label for history
		self.wallet.set_label(tx.txid(), text=desc, save=True)

		# broadcast transaction
		try:
			return self.window.network.broadcast_transaction2(tx)
		except Exception as e:
			self.print_error("error broadcasting tx: ", e)
			for tip in tips:
				tip.payment_status = "broadcast error" #: " + str(e)
				self.tiplist.updateTip(tip)


	def create_menu(self, position):
		"""creates context-menu for single or multiply selected items"""

		def doPay(tips: list):
			"""Start semi-automatic payment of a list of tips using the payto dialog"""
			self.print_error("paying tips: ", [t.id for t in tips])
			desc = "chaintip "
			desc_separator = ""
			payto = ""
			payto_separator = ""
			for tip in tips:
				if tip.recipient_address and tip.amount_bch and isinstance(tip.recipient_address, Address) and isinstance(tip.amount_bch, Decimal):
					payto += payto_separator + tip.recipient_address.to_string(Address.FMT_CASHADDR) + ', ' + str(tip.amount_bch)
					payto_separator = "\n"
					desc += f"{desc_separator}{tip.amount_bch} BCH to u/{tip.username} ({tip.chaintip_message.id})"
					desc_separator = ", "
				# else:
				# 	self.print_error("recipient_address: ", type(tip.recipient_address))
				# 	self.print_error("amount_bch: ", type(tip.amount_bch))
			self.print_error("  desc:", desc)
			self.print_error("  payto:", payto)

			w = self.parent # main_window
			w.payto_e.setText(payto)
			w.message_e.setText(desc)
			w.show_send_tab()

		def doAutoPay(tips: list):
			self.pay(tips)


		def doMarkRead(tips: list):
			"""call mark_read() on each of the 'tips' and remove them from tiplist"""

			for tip in tips:
				if tip.chaintip_message:
					tip.chaintip_message.mark_read()
					self.tiplist.dispatchRemoveTip(tip)

		col = self.currentColumn()
		column_title = self.headerItem().text(col)

		# put tips into array (single or multiple if selection)
		count_display_string = ""
		item = self.itemAt(position)
		if len(self.selectedItems()) <= 1:
			tips = [item.tip]
		else:
			tips = [s.tip for s in self.selectedItems()]
			count_display_string = f" ({len(tips)})"

		unpaid_tips = [t for t in tips if t.payment_status != 'paid' and t.amount_bch]
		unpaid_count_display_string = f" ({len(unpaid_tips)})" if len(unpaid_tips)>1 else "" 

		# create the context menu
		menu = QMenu()
		menu.addAction(_(f"mark read{count_display_string}"), lambda: doMarkRead(tips))
		if len(unpaid_tips) > 0:
			menu.addAction(_(f"pay{unpaid_count_display_string}..."), lambda: doPay(unpaid_tips))
			menu.addAction(_(f"autopay{unpaid_count_display_string}"), lambda: doAutoPay(unpaid_tips))
		
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

	def newTip(self, tip):
		#self.print_error("------- newTip", tip.chaintip_message.subject)
		if tip.recipient_address:
			self.tips_by_address[tip.recipient_address] = tip 
		TipListItem(tip)
		if c["use_categories"]:
			category_item = self.getCategoryItemForTip(tip)
			category_item.setExpanded(True)
			category_item.addChild(tip.tiplist_item)
		else:
			self.addTopLevelItem(tip.tiplist_item)

		self.checkPaymentStatus()
		self.potentiallyAutoPay([tip])


	def removeTip(self, tip):
		#self.print_error("------- removeTip", tip.chaintip_message.subject)
		if tip.recipient_address:
			del self.tips_by_address[tip.recipient_address]
		if hasattr(tip, 'tiplist_item'):
			if c["use_categories"]:
				category_item = self.getCategoryItemForTip(tip)
				category_item.removeChild(tip.tiplist_item)
			else:
				self.takeTopLevelItem(self.indexOfTopLevelItem(tip.tiplist_item))
		else:
			self.print_error("no tiplist_item")

	# 

	def potentiallyAutoPay(self, tips: list):
		if read_config(self.wallet, "autopay", False):
			tips_to_pay = [tip for tip in tips if tip.payment_status == 'amount parsed']
			self.pay(tips_to_pay)


	def checkPaymentStatus(self):
		txo = self.wallet.storage.get('txo', {})
		self.txo = {tx_hash: self.wallet.to_Address_dict(value)
			for tx_hash, value in txo.items()
			# skip empty entries to save memory and disk space
			if value}
		for txhash in txo:
			#self.print_error("  txhash", txhash)
			##tx = Transaction.tx_cache_get(txhash)
			tx = self.wallet.transactions.get(txhash)
			#txinfo = self.wallet.get_tx_info(tx)
			for txout in tx.outputs():
				#self.print_error("     txout", txout)
				#self.print_error("     address", txout[1])
				address = txout[1]
				try:
					tip = self.tips_by_address[address]
					#self.print_error("   ****** TIP", tip, "paid in txhash", txhash)
					if tip.payment_status != "paid":
						tip.payment_status = "paid"
						self.tiplist.updateTip(tip)
				except KeyError:
					continue
					#self.print_error("   cannot find tip for address", address)

					# if address == tip.recipient_address:
					# 	self.print_error("   ****** TIP PAID, txhash", txhash)
					# 	tip.payment_status = "paid"



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
