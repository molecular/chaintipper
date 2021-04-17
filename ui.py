
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

class TipListItem(QTreeWidgetItem):

	def __init__(self, o):
		if isinstance(o, list):
			#print_error("o: ", o)
			QTreeWidgetItem.__init__(self, o)
		elif isinstance(o, Tip):
			self.tip = o
			self.tip.tip_list_item = self
			self.__init__([
				o.id,
				format_time(o.chaintip_message.created_utc), 
				o.chaintip_message.author.name,
				o.chaintip_message.subject,
				o.tipping_comment_id,
				o.username,
				o.direction,
				str(o.amount_bch),
				o.recipient_address.to_ui_string() if o.recipient_address else None,
				o.tip_amount_text,
				str(o.tip_quantity),
				o.tip_unit,
				o.tip_op_return
			])
		else:
			QTreeWidgetItem.__init__(self)

class TipListWidget(PrintError, MyTreeWidget, TipListener):

	default_sort = MyTreeWidget.SortSpec(1, Qt.AscendingOrder)

	def __init__(self, parent):
		MyTreeWidget.__init__(self, parent, self.create_menu, [
								_('ID'), 
								_('Date'), 
								_('Author'), 
								_('Subject'), 
								_('TippingComment'), 
								_('UserName'), 
								_('Direction'), 
								_('AmountBCH'), 
								_('RecipientAddress'),
								_('TipAmountText'),
								_('TipQuantity'),
								_('TipUnit'),
								_('TipOnchainMessage')
							], 3, [],  # headers, stretch_column, editable_columns
							deferred_updates=True, save_sort_settings=True)
		self.print_error("TipListWidget.__init__()")
		self.setSelectionMode(QAbstractItemView.ExtendedSelection)
		self.setSortingEnabled(True)
		self.wallet = parent.wallet
		self.setIndentation(0)

		self.tiplist = TipList()
		self.tiplist.registerTipListener(self)
		self.reddit = Reddit(self.tiplist)

		# start reddit.sync() thread 
		self.t = threading.Thread(target=self.reddit.sync, daemon=True)
		self.t.start()		

	def abort(self):
		self.kill_join()
		self.switch_signal.emit()

	def kill_join(self):
		"""join or (after timeout) even kill any spawned threads""" 

		if self.t and self.t.is_alive():
			#self.sleeper.put(None)  # notify thread to wake up and exit
			if threading.current_thread() is not self.t:
				self.t.join(timeout=2.5)  # wait around a bit for it to die but give up if this takes too long

	def create_menu(self, position):
		"""creates context-menu for single or multiply selected items"""

		self.print_error("create_menu called")

		def doPay(tips):
			self.print_error("paying tips: ", [t.id for t in tips])
			desc = "chaintip "
			desc_separator = ""
			payto = ""
			payto_separator = ""
			for tip in tips:
				if tip.recipient_address and tip.amount_bch and isinstance(tip.recipient_address, Address) and isinstance(tip.amount_bch, Decimal):
					payto += payto_separator + tip.recipient_address.to_string(Address.FMT_CASHADDR) + ', ' + str(tip.amount_bch)
					payto_separator = "\n"
					desc += f"{desc_separator}{tip.amount_bch} BCH to u/{tip.username}"
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


		def doMarkRead(tips):
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
		if len(self.selectedItems()) <=1:
			tips = [item.tip]
		else:
			tips = [s.tip for s in self.selectedItems()]
			count_display_string = f" ({len(tips)})"

		# debug
		for tip in tips:
			self.print_error("  ", tip.username)

		# create the context menu
		menu = QMenu()
		menu.addAction(_(f"pay{count_display_string}"), lambda: doPay(tips))
		menu.addAction(_(f"mark read{count_display_string}"), lambda: doMarkRead(tips))
		
		menu.exec_(self.viewport().mapToGlobal(position))

	def newTip(self, tip):
		self.addTopLevelItem(TipListItem(tip))
		self.tipCheckPaymentStatus(tip)

	def removeTip(self, tip):
		self.takeTopLevelItem(self.indexOfTopLevelItem(tip.tip_list_item))

	def tipCheckPaymentStatus(self, tip):
		if tip.recipient_address:
			self.print_error("got address: ", tip.recipient_address.to_string(Address.FMT_LEGACY)) 

			txo = self.wallet.storage.get('txo', {})
			self.txo = {tx_hash: self.wallet.to_Address_dict(value)
				for tx_hash, value in txo.items()
				# skip empty entries to save memory and disk space
				if value}
			for tx in txo:
				self.print_error("txo", tx)

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

	def send_tx(self, recipient_address: Address, amount: Decimal, desc: str):
		# The message is intentionally untranslated, leave it like that
		self.parent.pay_to_URI('{pre}:{addr}?amount={amount}&message={desc}'
			.format(
				pre = networks.net.CASHADDR_PREFIX,
				addr = recipient_address.to_ui_string(),
				amount = str(amount),
				desc = desc
			)
		)


def _get_name(utxo) -> str:
	return "{}:{}".format(utxo['prevout_hash'], utxo['prevout_n'])


class LoadRWallet(MessageBoxMixin, PrintError, QWidget):

	def __init__(self, parent: ElectrumWindow, plugin, wallet_name, recipient_wallet=None, time=None, password=None):
		QWidget.__init__(self, parent)
		assert isinstance(parent, ElectrumWindow)
		self.password = password
		self.wallet = parent.wallet
		self.utxos = []  # populated by self.refresh_utxos() below
		self.weakWindow = Weak.ref(parent)  # grab a weak reference to the ElectrumWindow
		self.refresh_utxos()  # sets self.utxos
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
		vbox.addWidget(self.tiplist)

		if hasattr(parent, 'history_updated_signal'):
			# So that we get told about when new coins come in, and the UI updates itself
			parent.history_updated_signal.connect(self.refresh_utxos)
			parent.history_updated_signal.connect(self.transfer_changed)

	def refresh_utxos(self):
		parent = self.weakWindow()
		if parent:
			self.utxos = self.wallet.get_spendable_coins(None, parent.config)
			random.shuffle(self.utxos)  # randomize the coins' order

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

	def transfer_changed(self):
		self.print_error("transfer_changed()")


class TransferringUTXO(MessageBoxMixin, PrintError, MyTreeWidget):

	update_sig = pyqtSignal()

	class DataRoles(IntEnum):
		Time = Qt.UserRole+1
		Name = Qt.UserRole+2

	def __init__(self, parent, tab):
		MyTreeWidget.__init__(self, parent, self.create_menu,[
			_('Address'),
			_('Amount'),
			_('Time'),
			_('When'),
			_('Status'),
		], stretch_column=3, deferred_updates=True)
		self.tab = Weak.ref(tab)
		self.t0 = time.time()
		self.t0_last = None
		self._recalc_times(tab.times)
		self.print_error("transferring utxo")
		self.utxos = list(tab.utxos)
		self.main_window = parent
		self.setSelectionMode(QAbstractItemView.NoSelection)
		self.setSortingEnabled(False)
		self.sent_utxos = dict()
		self.failed_utxos = dict()
		self.sending = None
		self.check_icon = self._get_check_icon()
		self.fail_icon = self._get_fail_icon()
		self.update_sig.connect(self.update)
		self.monospace_font = QFont(MONOSPACE_FONT)
		self.italic_font = QFont(); self.italic_font.setItalic(True)
		self.timer = QTimer(self)
		self.timer.setSingleShot(False)
		self.timer.timeout.connect(self.update_sig)
		self.timer.start(2000)  # update every 2 seconds since the granularity of our "When" column is ~5 seconds
		self.wallet = tab.recipient_wallet

	def create_menu(self, position):
		pass

	@staticmethod
	def _get_check_icon() -> QIcon:
		if QFile.exists(":icons/confirmed.png"):
			# old EC version
			return QIcon(":icons/confirmed.png")
		else:
			# newer EC version
			return QIcon(":icons/confirmed.svg")

	@staticmethod
	def _get_fail_icon() -> QIcon:
		if QFile.exists(":icons/warning.png"):
			# current EC version
			return QIcon(":icons/warning.png")
		else:
			# future EC version
			return QIcon(":icons/warning.svg")

	def _recalc_times(self, times):
		if self.t0_last != self.t0:
			now = self.t0  # t0 is updated by thread as the actual start time
			self.times = [time.localtime(now + s) for s in times]
			self.times_secs = times
			self.t0_last = now

	def on_update(self):
		self.clear()
		tab = self.tab()
		if not tab or not self.wallet:
			return
		self._recalc_times(tab.times)
		base_unit = self.main_window.base_unit()
		for i, u in enumerate(self.utxos):
			address = u['address'].to_ui_string()
			value = self.main_window.format_amount(u['value'], whitespaces=True) + " " + base_unit
			name = _get_name(u)
			ts = self.sent_utxos.get(name)
			icon = None
			when_font = None
			when = ''
			is_sent = ts is not None
			if is_sent:
				status = _("Sent")
				when = age(ts, include_seconds=True)
				icon = self.check_icon
			else:
				failed_reason = self.failed_utxos.get(name)
				if failed_reason:
					status = _("Failed")
					when = failed_reason
					icon = self.fail_icon
					when_font = self.italic_font
				elif name == self.sending:
					status = _("Processing")
					when = status + " ..."
					when_font = self.italic_font
				else:
					status = _("Queued")
					when = age(max(self.t0 + self.times_secs[i], time.time()+0.5), include_seconds=True)

			item = SortableTreeWidgetItem([address, value, time.strftime('%H:%M', self.times[i]), when, status])
			item.setFont(0, self.monospace_font)
			item.setFont(1, self.monospace_font)
			item.setTextAlignment(1, Qt.AlignLeft)
			if icon:
				item.setIcon(4, icon)
			if when_font:
				item.setFont(3, when_font)
			self.addChild(item)


class Transfer(MessageBoxMixin, PrintError, QWidget):

	switch_signal = pyqtSignal()
	done_signal = pyqtSignal(str)
	set_label_signal = pyqtSignal(str, str)

	def __init__(self, parent, plugin, wallet_name, recipient_wallet, hours, password):
		QWidget.__init__(self, parent)
		self.wallet_name = wallet_name
		self.plugin = plugin
		self.password = password
		self.main_window = parent
		self.wallet = parent.wallet
		self.recipient_wallet = recipient_wallet

		cancel = False

		self.utxos = self.wallet.get_spendable_coins(None, parent.config)
		if not self.utxos:
			self.main_window.show_message(_("No coins were found in this wallet; cannot proceed with transfer."))
			cancel = True
		elif self.wallet.has_password():
			self.main_window.show_error(_(
				"Inter-Wallet Transfer plugin requires the password. "
				"It will be sending transactions from this wallet at a random time without asking for confirmation."))
			while True:
				# keep trying the password until it's valid or user cancels
				self.password = self.main_window.password_dialog()
				if not self.password:
					# user cancel
					cancel = True
					break
				try:
					self.wallet.check_password(self.password)
					break  # password was good, break out of loop
				except InvalidPassword as e:
					self.show_warning(str(e))  # show error, keep looping

		random.shuffle(self.utxos)
		self.times = self.randomize_times(hours)
		self.tu = TransferringUTXO(parent, self)
		vbox = QVBoxLayout()
		self.setLayout(vbox)
		vbox.addWidget(self.tu)
		self.tu.update()
		self.abort_but = b = QPushButton(_("Abort"))
		b.clicked.connect(self.abort)
		vbox.addWidget(b)
		self.switch_signal.connect(self.switch_signal_slot)
		self.done_signal.connect(self.done_slot)
		self.set_label_signal.connect(self.set_label_slot)
		self.sleeper = queue.Queue()
		if not cancel:
			self.t = threading.Thread(target=self.send_all, daemon=True)
			self.t.start()
		else:
			self.t = None
			self.setDisabled(True)
			# fire the switch signal as soon as we return to the event loop
			QTimer.singleShot(0, self.switch_signal)

	def filter(self, *args):
		"""This is here because searchable_list must define a filter method"""

	def diagnostic_name(self):
		return "InterWalletTransfer.Transfer"

	def randomize_times(self, hours):
		times = [random.randint(0, int(hours*3600)) for t in range(len(self.utxos))]
		times.insert(0, 0)  # first time is always immediate
		times.sort()
		del times[-1]  # since we inserted 0 at the beginning
		assert len(times) == len(self.utxos)
		return times

	def send_all(self):
		"""Runs in a thread"""
		def wait(timeout=1.0) -> bool:
			try:
				self.sleeper.get(timeout=timeout)
				# if we get here, we were notified to abort.
				return False
			except queue.Empty:
				'''Normal course of events, we slept for timeout seconds'''
				return True
		self.tu.t0 = t0 = time.time()
		ct, err_ct = 0, 0
		for i, t in enumerate(self.times):
			def time_left():
				return (t0 + t) - time.time()
			while time_left() > 0.0:
				if not wait(max(0.0, time_left())):  # wait for "time left" seconds
					# abort signalled
					return
			coin = self.utxos.pop(0)
			name = _get_name(coin)
			self.tu.sending = name
			self.tu.update_sig.emit()  # have the widget immediately display "Processing"
			while not self.recipient_wallet.is_fully_settled_down():
				''' We must wait for the recipient wallet to finish synching...
				Ugly hack.. :/ '''
				self.print_error("Receiving wallet is not yet up-to-date... waiting... ")
				if not wait(5.0):
					# abort signalled
					return
			err = self.send_tx(coin)
			if not err:
				self.tu.sent_utxos[name] = time.time()
				ct += 1
			else:
				self.tu.failed_utxos[name] = err
				err_ct += 1
			self.tu.sending = None
			self.tu.update_sig.emit()  # have the widget immediately show "Sent or "Failed"
		# Emit a signal which will end up calling switch_signal_slot
		# in the main thread; we need to do this because we must now update
		# the GUI, and we cannot update the GUI in non-main-thread
		# See issue #10
		if err_ct:
			self.done_signal.emit(_("Transferred {num} coins successfully, {failures} coins failed")
									.format(num=ct, failures=err_ct))
		else:
			self.done_signal.emit(_("Transferred {num} coins successfully").format(num=ct))

	def clean_up(self):
		if self.recipient_wallet:
			self.recipient_wallet.stop_threads()
		self.recipient_wallet = None
		if self.tu:
			self.tu.wallet = None
			if self.tu.timer:
				self.tu.timer.stop()
				self.tu.timer.deleteLater()
				self.tu.timer = None

	def switch_signal_slot(self):
		"""Runs in GUI (main) thread"""
		self.clean_up()
		self.plugin.switch_to(LoadRWallet, self.wallet_name, None, None, None)

	def done_slot(self, msg):
		self.abort_but.setText(_("Back"))
		self.show_message(msg)

	def send_tx(self, coin: dict) -> str:
		"""Returns the failure reason as a string on failure, or 'None'
		on success."""
		self.wallet.add_input_info(coin)
		inputs = [coin]
		recipient_address = self.recipient_wallet and self.recipient_wallet.get_unused_address(frozen_ok=False)
		self.print_error("recipient_address: ", recipient_address)
		if not recipient_address:
			self.print_error("Could not get recipient_address; recipient wallet may have been cleaned up, "
							 "aborting send_tx")
			return _("Unspecified failure")
		outputs = [(recipient_address.kind, recipient_address, coin['value'])]
		kwargs = {}
		if hasattr(self.wallet, 'is_schnorr_enabled'):
			# This EC version has Schnorr, query the flag
			kwargs['sign_schnorr'] = self.wallet.is_schnorr_enabled()
		# create the tx once to get a fee from the size
		tx = Transaction.from_io(inputs, outputs, locktime=self.wallet.get_local_height(), **kwargs)
		fee = tx.estimated_size()
		if coin['value'] - fee < self.wallet.dust_threshold():
			self.print_error("Resulting output value is below dust threshold, aborting send_tx")
			return _("Too small")
		# create the tx again, this time with the real fee
		outputs = [(recipient_address.kind, recipient_address, coin['value'] - fee)]
		tx = Transaction.from_io(inputs, outputs, locktime=self.wallet.get_local_height(), **kwargs)
		try:
			self.wallet.sign_transaction(tx, self.password)
		except InvalidPassword as e:
			return str(e)
		except Exception:
			return _("Unspecified failure")

		self.set_label_signal.emit(tx.txid(),
			_("Inter-Wallet Transfer {amount} -> {address}").format(
				amount=self.main_window.format_amount(coin['value']) + " " + self.main_window.base_unit(),
				address=recipient_address.to_ui_string()
		))
		try:
			self.main_window.network.broadcast_transaction2(tx)
		except Exception as e:
			self.print_error("Error broadcasting tx:", repr(e))
			return (e.args and e.args[0]) or _("Unspecified failure")
		self.recipient_wallet.frozen_addresses.add(recipient_address)
		self.recipient_wallet.create_new_address(False)
		return None

	def set_label_slot(self, txid: str, label: str):
		"""Runs in GUI (main) thread"""
		self.wallet.set_label(txid, label)

	def abort(self):
		self.kill_join()
		self.switch_signal.emit()

	def kill_join(self):
		if self.t and self.t.is_alive():
			self.sleeper.put(None)  # notify thread to wake up and exit
			if threading.current_thread() is not self.t:
				self.t.join(timeout=2.5)  # wait around a bit for it to die but give up if this takes too long

	def on_delete(self):
		pass

	def on_update(self):
		pass
