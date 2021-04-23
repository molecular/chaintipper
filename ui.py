
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
from electroncash import keystore
from electroncash.storage import WalletStorage
from electroncash.keystore import Hardware_KeyStore
from electroncash.wallet import Standard_Wallet, Multisig_Wallet
from electroncash.address import Address
from electroncash import networks

from .model import Tip, TipList, TipListener
from .reddit import Reddit
from .config import c

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
				o.type,
				o.payment_status,
				#o.chaintip_message.author.name,
				o.chaintip_message.subject,
				o.tipping_comment_id,
				o.username,
				#o.direction,
				str(o.amount_bch),
				#o.recipient_address.to_ui_string() if o.recipient_address else None,
				o.tip_amount_text,
				str(o.tip_quantity),
				o.tip_unit,
				o.status
			])
		else:
			QTreeWidgetItem.__init__(self)

class TipListWidget(PrintError, MyTreeWidget, TipListener):

	default_sort = MyTreeWidget.SortSpec(1, Qt.AscendingOrder)

	def __init__(self, parent):
		MyTreeWidget.__init__(self, parent, self.create_menu, [
								#_('ID'), 
								_('Date'),
								_('Type'),
								_('Payment Status'), 
								#_('Author'), 
								_('Subject'), 
								_('Tip Comment'), 
								_('Recipient'), 
								#_('Direction'), 
								_('Amount (BCH)'), 
								#_('Recipient Address'),
								_('Tip Amount Text'),
								_('Tip Quantity'),
								_('Tip Unit'),
								_('Status'),
							], 1, [6],  # headers, stretch_column, editable_columns
							deferred_updates=True, save_sort_settings=True)
		self.print_error("TipListWidget.__init__()")
		self.setSelectionMode(QAbstractItemView.ExtendedSelection)
		self.setSortingEnabled(True)
		self.wallet = parent.wallet
		self.setIndentation(0)

		self.tiplist = TipList()
		self.tiplist.registerTipListener(self)
		self.tips_by_address = dict()

		if c["use_categories"]:
			self.outgoing_items = QTreeWidgetItem([_("outgoing")])
			self.addTopLevelItem(self.outgoing_items)
			self.incoming_items = QTreeWidgetItem([_("incoming")])
			self.addTopLevelItem(self.incoming_items)
			self.other_items = QTreeWidgetItem([_("other messages")])
			#self.addTopLevelItem(self.other_items)

		self.reddit = Reddit(self.tiplist)
		self.reddit_thread = QThread()
		self.reddit.moveToThread(self.reddit_thread)
		self.reddit_thread.started.connect(self.reddit.run)
		self.reddit.new_tip.connect(self.tiplist.dispatchNewTip)
		self.reddit_thread.start()

	def abort(self):
		self.reddit_thread.quit()
		self.switch_signal.emit()

	def create_menu(self, position):
		"""creates context-menu for single or multiply selected items"""

		self.print_error("create_menu called")

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
				else:
					self.print_error("recipient_address: ", type(tip.recipient_address))
					self.print_error("amount_bch: ", type(tip.amount_bch))
			self.print_error("  desc:", desc)
			self.print_error("  payto:", payto)

			w = self.parent # main_window
			w.payto_e.setText(payto)
			w.message_e.setText(desc)
			w.show_send_tab()


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

		# debug
		for tip in tips:
			self.print_error("  ", tip.username)

		# create the context menu
		menu = QMenu()
		menu.addAction(_(f"mark read{count_display_string}"), lambda: doMarkRead(tips))
		if len(unpaid_tips) > 0:
			menu.addAction(_(f"pay{unpaid_count_display_string}..."), lambda: doPay(unpaid_tips))
		
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
		self.print_error("------- newTip", tip.chaintip_message.subject)
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


	def removeTip(self, tip):
		self.print_error("------- removeTip", tip.chaintip_message.subject)
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

class LoadRWallet(MessageBoxMixin, PrintError, QWidget):

	def __init__(self, parent: ElectrumWindow, plugin, wallet_name, recipient_wallet=None, time=None, password=None):
		QWidget.__init__(self, parent)
		assert isinstance(parent, ElectrumWindow)
		self.password = password
		self.wallet = parent.wallet
		self.weakWindow = Weak.ref(parent)  # grab a weak reference to the ElectrumWindow
		for x in range(10):
			name = 'tmp_wo_wallet' + ''.join(random.choices(string.ascii_letters + string.digits, k=10))
			self.file = os.path.join(tempfile.gettempdir(), name)
			if not os.path.exists(self.file):
				break
		else:
			raise RuntimeError('Could not find a unique temp file in tmp directory', tempfile.gettempdir())
		self.tmp_pass = ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))
		self.storage = None
		self.recipient_wallet = None
		self.keystore = None
		self.plugin = plugin
		self.network = parent.network
		self.wallet_name = wallet_name
		self.keystore = None


		self.print_error("ui loading")

		vbox = QVBoxLayout()
		self.setLayout(vbox)
		l2 = QLabel(f'wallet_name: {self.wallet_name}')
		vbox.addWidget(l2)
		l2.setTextInteractionFlags(Qt.TextSelectableByMouse)

		self.tiplist = TipListWidget(parent)
		self.tiplist.checkPaymentStatus()
		vbox.addWidget(self.tiplist)

		if hasattr(parent, 'history_updated_signal'):
			# So that we get told about when new coins come in, and the UI updates itself
			parent.history_updated_signal.connect(self.update_payment_statuses)

	def update_payment_statuses(self):
		if hasattr(self, 'tiplist'):
			self.tiplist.checkPaymentStatus()

	def filter(self, *args):
		"""This is here because searchable_list must define a filter method"""

	def showEvent(self, e):
		super().showEvent(e)
		# if not self.network and self.isEnabled():
		# 	self.show_warning(_("The Inter-Wallet Transfer plugin cannot function in offline mode. "
		# 						"Restart Electron Cash in online mode to proceed."))
		# 	self.setDisabled(True)

	@staticmethod
	def delete_temp_wallet_file(file):
		"""deletes the wallet file"""
		if file and os.path.exists(file):
			try:
				os.remove(file)
				print_error("[InterWalletTransfer] Removed temp file", file)
			except Exception as e:
				print_error("[InterWalletTransfer] Failed to remove temp file", file, "error: ", repr(e))

	def transfer(self):
		self.show_message(_("You should not use either wallet during the transfer. Leave Electron Cash active. "
							"The plugin ceases operation and will have to be re-activated if Electron Cash "
							"is stopped during the operation."))
		self.storage = WalletStorage(self.file)
		self.storage.set_password(self.tmp_pass, encrypt=True)
		self.storage.put('keystore', self.keystore.dump())
		self.recipient_wallet = Standard_Wallet(self.storage)
		self.recipient_wallet.start_threads(self.network)
		# comment the below out if you want to disable auto-clean of temp file
		# otherwise the temp file will be auto-cleaned on app exit or
		# on the recepient_wallet object's destruction (when refct drops to 0)
		Weak.finalize(self.recipient_wallet, self.delete_temp_wallet_file, self.file)
		self.plugin.switch_to(Transfer, self.wallet_name, self.recipient_wallet, float(self.time_e.text()),
								self.password)

