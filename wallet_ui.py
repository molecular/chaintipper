from PyQt5 import QtGui
from PyQt5 import QtCore
from PyQt5.QtWidgets import QMessageBox
from PyQt5.QtWidgets import (
	QAction, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QGroupBox, QCheckBox, 
	QStackedLayout, QWidget, QGridLayout, QRadioButton, QDoubleSpinBox, QSpinBox,
	QSizePolicy, QLineEdit
)
from PyQt5.QtCore import Qt

import weakref
import decimal
from datetime import datetime

from electroncash.i18n import _
from electroncash_gui.qt import ElectrumWindow, MessageBoxMixin
from electroncash_gui.qt.util import (
	destroyed_print_error,
	Buttons, CancelButton, CloseButton, ColorScheme, OkButton, WaitingDialog, 
	WindowModalDialog
)
from electroncash_gui.qt.amountedit import BTCAmountEdit
from electroncash_gui.qt.main_window import StatusBarButton
from electroncash.util import finalization_print_error, inv_dict
from electroncash.util import PrintError
from electroncash.wallet import Abstract_Wallet

from .qresources import qInitResources

from . import fullname
from .reddit import Reddit
from .model import TipList, TipListener
from .tiplist import TipListWidget
from .util import read_config, write_config, commit_config
from .config import c, amount_config_to_rich_text
from .blockchain_watcher import BlockchainWatcher
from .autopay import AutoPay

icon_chaintip = QtGui.QIcon(":icons/chaintip.svg")
icon_chaintip_gray = QtGui.QIcon(":icons/chaintip_gray.svg")



class WalletUI(MessageBoxMixin, PrintError, QWidget):
	"""
	Encapsulates UI for a wallet and associated window.
	Plugin class will instantiate one WalletUI per wallet.
	"""
	def __init__(self, wallet: Abstract_Wallet, window: ElectrumWindow):
		QWidget.__init__(self, window)
		self.window = window
		self.wallet = wallet
		self.wallet_name = self.wallet.basename()

		self.widgets = weakref.WeakSet() # widgets we made, that need to be hidden & deleted when plugin is disabled
		self.wallet_tab = None
		self.tab = None
		self.previous_tab_index = None
		self.reddit = None
		self.reddit_thread = None
		self.tiplist = None

		self.old_debug_stats = ""

		# layout
		self.vbox = vbox = QVBoxLayout()
		vbox.setContentsMargins(0, 0, 0, 0)
		self.setLayout(vbox)

		# write initial chaintipper_activation_time
		activation_t = read_config(self.wallet, "activation_time", datetime.utcnow().timestamp())

		# more setup
		self.setup_button()

	def debug_stats(self):
		return "              WalletUI: "

	def print_debug_stats(self):
		s = "\n" + self.debug_stats() + "\n"
		if hasattr(self, "tiplist") and self.tiplist: 
			s += "   " + self.tiplist.debug_stats() + "\n"
		if hasattr(self, "blockchain_watcher") and self.blockchain_watcher:
			s += "   " + self.blockchain_watcher.debug_stats() + "\n"
		if hasattr(self, "autopay") and self.autopay:
			s += "   " + self.autopay.debug_stats() + "\n"
		if hasattr(self, "reddit") and self.reddit:
			s += "   " + self.reddit.debug_stats() + "\n"

		if s != self.old_debug_stats:
			self.old_debug_stats = s
			self.print_error(s)

	def kill_join(self):
		self.print_error("kill_join()")
		self.deactivate()

	def setup_button(self):
		# setup chaintipper button
		sbmsg = _('ChainTipper disabled, click to enable')
		self.sbbtn = ChaintipperButton(self)

		# bit of a dirty hack, to insert our status bar icon (always using index 4, should put us just after the password-changer icon)
		sb = self.window.statusBar()
		sb.insertPermanentWidget(4, self.sbbtn)
		self.widgets.add(self.sbbtn)
		self.window._chaintipper_button = weakref.ref(self.sbbtn)

	def setup_reddit(self):
		"""log in to reddit, start a thread and begin receiving messages"""
		if not self.reddit.login():
			# login fails, deactivate, inform user and open settings dialog
			self.print_error("reddit.login() returned False")
			# self.window.show_critical(_("Reddit authentication failed.\n\nDeactivating chaintipper on this wallet.\n\nYou can activate it to try again."))
			if self.sbbtn:
				self.sbbtn.set_active(False) # abort activation and toggle back to inactive
				#self.show_wallet_settings()
		else:
			self.reddit.start_thread()
			self.reddit.new_tip.connect(self.tiplist.addTip)
			self.reddit.dathread.finished.connect(self.reddit_thread_finished)

			# So that we get told about when new coins come in, and the UI updates itself
			# if hasattr(self.window, 'history_updated_signal'):
			# 	self.window.history_updated_signal.connect(self.tiplist_widget.checkPaymentStatus)

	def reddit_thread_finished(self):
		self.print_error("reddit thread finished")
		self.sbbtn.set_active(False)

	def activate(self):
		"""
		Will be called by the ChaintipperButton on activation.
		Constructs UI and starts reddit thread
		"""

		# wait for wallet to sync to help avoid spending spent utxos
		self.wallet.wait_until_synchronized()

		self.reddit = Reddit(self)
		self.add_ui()
		self.setup_reddit()
		self.refresh_ui()
		self.show_chaintipper_tab()

	def deactivate(self):
		"""
		Will be called by the ChaintipperButton on deactivation.
		Deconstructs UI and winds down reddit thread
		"""
		if self.reddit:
			self.reddit.quit()
		self.remove_ui()
		self.show_previous_tab()
		# self.close_wallet(wallet) # TODO: this might be misuse

	def show_chaintipper_tab(self):
		"""switch main window to ChainTipper tab"""
		if self.tab:
			self.previous_tab_index = self.window.tabs.currentIndex()
			self.window.tabs.setCurrentIndex(self.window.tabs.indexOf(self.tab))

	def show_previous_tab(self):
		"""switch main window back to tab selected when show_chaintipper_tab() was called"""
		self.print_error("previous tab index:", self.previous_tab_index)
		if self.previous_tab_index != None:
			self.window.tabs.setCurrentIndex(self.previous_tab_index)
			self.previous_tab_index = None

	def add_ui(self):
		"""construct tab with tiplist widget and add it to window"""
		self.tiplist = TipList()
		self.autopay = AutoPay(self.wallet, self.tiplist)
		self.blockchain_watcher = BlockchainWatcher(self.wallet, self.tiplist)
		self.tiplist_widget = TipListWidget(self, self.window, self.wallet, self.tiplist, self.reddit)
		#self.tiplist_widget.checkPaymentStatus()
		self.vbox.addWidget(self.tiplist_widget)

		self.tab = self.window.create_list_tab(self)
		self.window.tabs.addTab(self.tab, icon_chaintip, _('ChainTipper'))

	def remove_ui(self):
		"""deconstruct the UI created in add_ui(), leaving self.vbox"""
		if hasattr(self, "autopay") and self.autopay:
			del self.autopay
		if hasattr(self, "blockchain_watcher") and self.blockchain_watcher:
			del self.blockchain_watcher
		if self.vbox:
			self.vbox.removeWidget(self.tiplist_widget)
		if self.tiplist:
			del self.tiplist
		if self.tab:
			self.window.tabs.removeTab(self.window.tabs.indexOf(self.tab))
#			self.tab.deleteLater()
		self.tab = None

	# TODO: not sure this is necessary
	def refresh_ui(self):
		if self.tab: 
			self.tab.update()

	def show_settings_dialog(self):
		self.print_error("show_settings_dialog() not implemented")

	def close(self):
		self.print_error("walletui.close() called")

	def show_wallet_settings(self):
		win = getattr(self.wallet, '_chaintipper_settings_window', None)
		if not win:
			#win = WalletSettingsDialog(self, ChaintipperButton.get_suitable_dialog_window_parent(self.wallet))
			win = WalletSettingsDialog(self, self.window)
			self.widgets.add(self.window)  # adding to widgets list ensures if plugin is unloaded while dialog is up, that the dialog will be killed.
		win.show()
		win.raise_()



class ChaintipperButton(StatusBarButton, PrintError):

	def __init__(self, wallet_ui):
		super().__init__(icon_chaintip, fullname, self.toggle_active)

		self.is_active = False

		self.wallet_ui = wallet_ui

		self.action_toggle = QAction(_("Active on this wallet"))
		self.action_toggle.setCheckable(True)
		self.action_toggle.triggered.connect(self.toggle_active)

		action_separator1 = QAction(self); action_separator1.setSeparator(True)

		action_wsettings = QAction(_("Wallet-specific Settings..."), self)
		action_wsettings.triggered.connect(self.wallet_ui.show_wallet_settings)

		action_settings = QAction(_("Forget Reddit Authorization (e.g. to switch reddit account)"), self)
		action_settings.triggered.connect(self.disconnect_reddit)

		action_settings2 = QAction(_("(TEMPORARY) Mark unread some chaintip messages/comments"), self)
		action_settings2.triggered.connect(self.unread_messages)

		# action_settings = QAction(_("Global Settings..."), self)
		# action_settings.triggered.connect(self.wallet_ui.plugin.show_settings_dialog)

		action_separator2 = QAction(self); action_separator2.setSeparator(True)

		show_monikers = QAction(_("Show Amount Monikers"), self)
		show_monikers.triggered.connect(self.showMonikers)

		self.addActions([
			self.action_toggle, 
			action_separator1,
			action_wsettings,
			action_settings,
			action_settings2,
			action_separator2, 
			show_monikers
		])

		self.setContextMenuPolicy(Qt.ActionsContextMenu)

		self.update_state()

	def showMonikers(self):
		self.wallet_ui.msg_box(
			icon = QMessageBox.Question,
			parent = self.wallet_ui.window,
			title = _("Amount Monikers"),
			rich_text = True,
			text = amount_config_to_rich_text()
		)

	def update_state(self):
		self.action_toggle.setChecked(self.is_active)
		if self.is_active:
			self.setIcon(icon_chaintip)
			self.setToolTip(_('ChainTipper - active on wallet "{wallet_name}"').format(wallet_name=self.wallet_ui.wallet_name))
			self.setStatusTip(_('ChainTipper - Active on wallet "{wallet_name}"').format(wallet_name=self.wallet_ui.wallet_name))
			self.wallet_ui.activate()
		else:
			self.setIcon(icon_chaintip_gray)
			self.setToolTip(_('ChainTipper - not active on wallet "{wallet_name}"').format(wallet_name=self.wallet_ui.wallet_name))
			self.setStatusTip(_('ChainTipper - Inactive (click to activate on wallet "{wallet_name}")').format(wallet_name=self.wallet_ui.wallet_name))
			self.wallet_ui.deactivate()

	def toggle_active(self):
		if self.is_active:
			self.is_active = False
		else:
			self.is_active = True
		self.update_state()

	def set_active(self, active):
		if self.is_active != active:
			self.is_active = active
			self.update_state()

	def disconnect_reddit(self):
		self.wallet_ui.reddit.disconnect()
		self.set_active(False)

	def unread_messages(self):
		if self.wallet_ui.reddit:
			self.wallet_ui.reddit.markChaintipMessagesUnread(100)

class WalletSettingsDialog(WindowModalDialog, PrintError, MessageBoxMixin):
	"""Dialog for wallet-specific settings"""

	def __init__(self, wallet_ui, parent):
		super().__init__(parent=parent, title=_("ChainTipper - Wallet-specific Settings"))
		self.setWindowIcon(icon_chaintip)
		self.wallet_ui = wallet_ui
		self.wallet = self.wallet_ui.wallet # TODO: remove and refactor to increase code clarity?

		self.idx2confkey = dict()   # int -> 'normal', 'consolidate', etc..
		self.confkey2idx = dict()   # str 'normal', 'consolidate', etc -> int

		assert not hasattr(self.wallet, '_chaintipper_settings_window')
		main_window = self.wallet.weak_window()
		assert main_window
		self.wallet._chaintipper_settings_window = self

		main_layout = QVBoxLayout(self)

		# header
		#main_layout.addWidget(QLabel(_('ChainTipper - settings for wallet "{wallet_name}"').format(wallet_name=self.wallet_ui.wallet_name)), 0, 0, Qt.AlignRight)

		# --- group for startup settings
		gbox = QGroupBox(_("Behaviour"))
		grid = QGridLayout(gbox)
		main_layout.addWidget(gbox)


		# active when wallet opens
		self.cb_activate_on_open = QCheckBox(_("Activate ChainTipper when wallet '{wallet_name}'' is opened.").format(wallet_name=self.wallet_ui.wallet_name))
		self.cb_activate_on_open.setChecked(read_config(self.wallet, "activate_on_wallet_open", c["default_activate_on_wallet_open"], commit=False))
		def on_cb_activate_on_open():
			write_config(self.wallet, "activate_on_wallet_open", self.cb_activate_on_open.isChecked(), commit=False)
		self.cb_activate_on_open.stateChanged.connect(on_cb_activate_on_open)
		grid.addWidget(self.cb_activate_on_open)

		# mark read paid tips
		self.cb_mark_read_paid_tips = QCheckBox(_("Mark associated messages as read when a Tip is paid."))
		self.cb_mark_read_paid_tips.setChecked(read_config(self.wallet, "mark_read_paid_tips", c["default_mark_read_paid_tips"], commit=False))
		def on_cb_mark_read_paid_tips():
			write_config(self.wallet, "mark_read_paid_tips", self.cb_mark_read_paid_tips.isChecked(), commit=False)
		self.cb_mark_read_paid_tips.stateChanged.connect(on_cb_mark_read_paid_tips)
		grid.addWidget(self.cb_mark_read_paid_tips)

		# --- group Default Tip Amount ------------------------------------------------------------------------------------------

		main_layout.addStretch(1)

		gbox = QGroupBox(_("Default Tip Amount (used when amount parsing fails)"))
		grid = QGridLayout(gbox)
		main_layout.addWidget(gbox)

		# amount
		grid.addWidget(QLabel(_('Amount')), 0, 1, Qt.AlignRight)
		self.default_amount = QLineEdit()
		self.default_amount.setText(read_config(self.wallet, "default_amount", c["default_amount"], commit=False))
		def on_default_amount():
			try:
				self.default_amount.setText(str(decimal.Decimal(self.default_amount.text())))
			except decimal.InvalidOperation as e:
				self.show_error(_("Cannot parse {string} as decimal number. Please try again.").format(string=self.default_amount.text()))
				self.default_amount.setText(read_config(self.wallet, "default_amount", c["default_amount"], commit=False))
			write_config(self.wallet, "default_amount", self.default_amount.text(), commit=False)
		self.default_amount.editingFinished.connect(on_default_amount)
		grid.addWidget(self.default_amount, 0, 2)

		# currency
		self.currencies = sorted(self.wallet_ui.window.fx.get_currencies(self.wallet_ui.window.fx.get_history_config()))
		grid.addWidget(QLabel(_('Currency')), 1, 1, Qt.AlignRight)
		self.default_amount_currency = QComboBox()
		self.default_amount_currency.addItems(self.currencies)
		self.default_amount_currency.setCurrentIndex(
			self.default_amount_currency.findText(
				read_config(self.wallet, "default_amount_currency", c["default_amount_currency"], commit=False)
			)
		)
		def on_default_amount_currency():
			write_config(self.wallet, "default_amount_currency", self.currencies[self.default_amount_currency.currentIndex()], commit=False)
		self.default_amount_currency.currentIndexChanged.connect(on_default_amount_currency)
		grid.addWidget(self.default_amount_currency, 1, 2)


		# --- group Linked Default Tip Amount ----------------------------------------------------------------------------------

		main_layout.addStretch(1)

		self.gbox_linked_amount = QGroupBox(_("Special Linked Default Tip Amount (used when amount parsing fails and recipient has linked an address)"))
		self.gbox_linked_amount.setCheckable(True)
		self.gbox_linked_amount.setChecked(read_config(self.wallet, "use_linked_amount", c["default_use_linked_amount"]))
		grid = QGridLayout(self.gbox_linked_amount)
		main_layout.addWidget(self.gbox_linked_amount)
		def on_gbox_linked_amount():
			write_config(self.wallet, "use_linked_amount", self.gbox_linked_amount.isChecked(), commit=False)
		self.gbox_linked_amount.toggled.connect(on_gbox_linked_amount)

		# amount
		grid.addWidget(QLabel(_('Amount')), 0, 1, Qt.AlignRight)
		self.default_linked_amount = QLineEdit()
		self.default_linked_amount.setText(read_config(self.wallet, "default_linked_amount", c["default_linked_amount"], commit=False))
		def on_default_linked_amount():
			try:
				self.default_linked_amount.setText(str(decimal.Decimal(self.default_linked_amount.text())))
			except decimal.InvalidOperation as e:
				self.show_error(_("Cannot parse {string} as decimal number. Please try again.").format(string=self.default_linked_amount.text()))
				self.default_linked_amount.setText(read_config(self.wallet, "default_linked_amount", c["default_linked_amount"], commit=False))
			write_config(self.wallet, "default_linked_amount", self.default_linked_amount.text(), commit=False)
		self.default_linked_amount.editingFinished.connect(on_default_linked_amount)
		grid.addWidget(self.default_linked_amount, 0, 2)

		# currency
		self.currencies = sorted(self.wallet_ui.window.fx.get_currencies(self.wallet_ui.window.fx.get_history_config()))
		grid.addWidget(QLabel(_('Currency')), 1, 1, Qt.AlignRight)
		self.default_linked_amount_currency = QComboBox()
		self.default_linked_amount_currency.addItems(self.currencies)
		self.default_linked_amount_currency.setCurrentIndex(
			self.default_linked_amount_currency.findText(
				read_config(self.wallet, "default_linked_amount_currency", c["default_linked_amount_currency"], commit=False)
			)
		)
		def on_default_linked_amount_currency():
			write_config(self.wallet, "default_linked_amount_currency", self.currencies[self.default_linked_amount_currency.currentIndex()], commit=False)
		self.default_linked_amount_currency.currentIndexChanged.connect(on_default_linked_amount_currency)
		grid.addWidget(self.default_linked_amount_currency, 1, 2)


		# --- group autopay ---------------------------------------------------------------------------------------------------

		main_layout.addStretch(1)

		self.gbox_autopay = QGroupBox(_("AutoPay - Automatically pay unpaid tips"))
		self.gbox_autopay.setCheckable(True)
		self.gbox_autopay.setChecked(read_config(self.wallet, "autopay", c["default_autopay"]))
		vbox = QVBoxLayout(self.gbox_autopay)
		main_layout.addWidget(self.gbox_autopay)
		def on_gbox_autopay():
			write_config(self.wallet, "autopay", self.gbox_autopay.isChecked(), commit=False)
			#on_cb_autopay_limit()
		self.gbox_autopay.toggled.connect(on_gbox_autopay)

		# disallow autopay when default amount is used
		self.cb_autopay_disallow_default = QCheckBox(_("Disallow AutoPay when Default Tip Amount is used"))
		self.cb_autopay_disallow_default.setChecked(read_config(self.wallet, "autopay_disallow_default", c["default_autopay_disallow_default"], commit=False))
		def on_cb_autopay_disallow_default():
			write_config(self.wallet, "autopay_disallow_default", self.cb_autopay_disallow_default.isChecked(), commit=False)
		self.cb_autopay_disallow_default.stateChanged.connect(on_cb_autopay_disallow_default)
		vbox.addWidget(self.cb_autopay_disallow_default)

		# autopay limit checkbox
		self.cb_autopay_limit = QCheckBox(_("Limit AutoPay Amount"))
		self.cb_autopay_limit.setChecked(read_config(self.wallet, "autopay_use_limit", c["default_autopay_use_limit"], commit=False))
		def on_cb_autopay_limit():
			self.autopay_limit_bch_label.setEnabled(self.gbox_autopay.isChecked() and self.cb_autopay_limit.isChecked())
			self.autopay_limit_bch.setEnabled(self.gbox_autopay.isChecked() and self.cb_autopay_limit.isChecked())
			write_config(self.wallet, "autopay_use_limit", self.cb_autopay_limit.isChecked(), commit=False)
		self.cb_autopay_limit.stateChanged.connect(on_cb_autopay_limit)
		vbox.addWidget(self.cb_autopay_limit)

		# autopay limit (amount)
		hbox = QHBoxLayout()
		vbox.addLayout(hbox)
		self.autopay_limit_bch_label = QLabel(_('AutoPay Limit (BCH)'))
		hbox.addWidget(self.autopay_limit_bch_label, 10, Qt.AlignRight)
		self.autopay_limit_bch = QLineEdit()
		self.autopay_limit_bch.setText(read_config(self.wallet, "autopay_limit_bch", c["default_autopay_limit_bch"], commit=False))
		def on_autopay_limit_bch():
			write_config(self.wallet, "autopay_limit_bch", self.autopay_limit_bch.text(), commit=False)
		self.autopay_limit_bch.editingFinished.connect(on_autopay_limit_bch)
		hbox.addWidget(self.autopay_limit_bch, 40)

		# ensure correct enable state
		#on_cb_autopay()


		# close button
		cbut = CloseButton(self)
		main_layout.addLayout(Buttons(cbut))
		cbut.setDefault(False)
		cbut.setAutoDefault(False)

	def closeEvent(self, event):
		super().closeEvent(event)
		commit_config(self.wallet)
		if event.isAccepted():
			self.setParent(None)
			del self.wallet._chaintipper_settings_window
		if self.wallet_ui.reddit != None:
			self.wallet_ui.reddit.triggerRefreshTips() # TODO why?!? <- to re-trigger autopay, for example

	def showEvent(self, event):
		super().showEvent(event)
		# if event.isAccepted():
		# 	self.refresh()
