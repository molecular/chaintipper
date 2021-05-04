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
from .model import TipList
from .tiplist import TipListWidget
from .util import read_config, write_config
from .config import c, amount_config_to_rich_text

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

		# layout
		self.vbox = vbox = QVBoxLayout()
		vbox.setContentsMargins(0, 0, 0, 0)
		self.setLayout(vbox)

		# more setup
		self.setup_button()

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
		self.reddit = Reddit(self)
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
			if hasattr(self.window, 'history_updated_signal'):
				self.window.history_updated_signal.connect(self.tiplist_widget.checkPaymentStatus)

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

		self.add_ui()
		self.setup_reddit()
		self.refresh_ui()
		self.show_chaintipper_tab()

	def deactivate(self):
		"""
		Will be called by the ChaintipperButton on deactivation.
		Deconstructs UI and winds down reddit thread
		"""
		self.remove_ui()
		self.show_previous_tab()
		if self.reddit:
			self.reddit.quit()
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
		self.tiplist_widget = TipListWidget(self.window, self.wallet, self.tiplist)
		self.tiplist_widget.checkPaymentStatus()
		self.vbox.addWidget(self.tiplist_widget)

		self.tab = self.window.create_list_tab(self)
		self.window.tabs.addTab(self.tab, icon_chaintip, _('ChainTipper'))

	def remove_ui(self):
		"""deconstruct the UI created in add_ui(), leaving self.vbox"""
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
		self.print_error("set_active(", active, "), is_active: ", self.is_active)
		if self.is_active != active:
			self.is_active = active
			self.update_state()

	def disconnect_reddit(self):
		self.wallet_ui.reddit.disconnect()
		self.set_active(False)



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


		# # reddit credentials
		# gbox = QGroupBox(_("Reddit Credentials"))
		# grid = QGridLayout(gbox)
		# main_layout.addWidget(gbox)

		# # reddit username
		# grid.addWidget(QLabel(_('Username')), 0, 0, Qt.AlignRight)
		# self.reddit_username = QLineEdit()
		# self.reddit_username.setText(read_config(self.wallet, "reddit_username"))
		# def on_reddit_username():
		# 	write_config(self.wallet, "reddit_username", self.reddit_username.text())
		# self.reddit_username.editingFinished.connect(on_reddit_username)
		# grid.addWidget(self.reddit_username, 0, 1)

		# # reddit password
		# grid.addWidget(QLabel(_('Password')), 1, 0, Qt.AlignRight)
		# self.reddit_password = QLineEdit()
		# self.reddit_password.setEchoMode(QLineEdit.Password)
		# self.reddit_password.setText(read_config(self.wallet, "reddit_password"))
		# def on_reddit_password():
		# 	write_config(self.wallet, "reddit_password", self.reddit_password.text())
		# self.reddit_password.editingFinished.connect(on_reddit_password)
		# grid.addWidget(self.reddit_password, 1, 1)

		# --- group for startup settings
		gbox = QGroupBox(_("Startup Settings"))
		grid = QGridLayout(gbox)
		main_layout.addWidget(gbox)


		# active when wallet opens
		self.cb_activate_on_open = QCheckBox(_("Activate ChainTipper when wallet '{wallet_name}'' is opened.").format(wallet_name=self.wallet_ui.wallet_name))
		self.cb_activate_on_open.setChecked(read_config(self.wallet, "activate_on_wallet_open", False))
		def on_cb_activate_on_open():
			write_config(self.wallet, "activate_on_wallet_open", self.cb_activate_on_open.isChecked())
		self.cb_activate_on_open.stateChanged.connect(on_cb_activate_on_open)
		grid.addWidget(self.cb_activate_on_open)

		# --- group Default Tip Amount
		gbox = QGroupBox(_("Default Tip Amount (used when amount parsing doesn\'t yield a result)"))
		grid = QGridLayout(gbox)
		main_layout.addWidget(gbox)

		# amount
		grid.addWidget(QLabel(_('Amount')), 0, 0, Qt.AlignRight)
		self.default_amount = QLineEdit()
		self.default_amount.setText(read_config(self.wallet, "default_amount", c["default_amount"]))
		def on_default_amount():
			try:
				self.default_amount.setText(str(decimal.Decimal(self.default_amount.text())))
			except decimal.InvalidOperation as e:
				self.show_error(_("Cannot parse {string} as decimal number. Please try again.").format(string=self.default_amount.text()))
				self.default_amount.setText(read_config(self.wallet, "default_amount", c["default_amount"]))
			write_config(self.wallet, "default_amount", self.default_amount.text())
		self.default_amount.editingFinished.connect(on_default_amount)
		grid.addWidget(self.default_amount, 0, 1)

		# currency
		self.currencies = sorted(self.wallet_ui.window.fx.get_currencies(self.wallet_ui.window.fx.get_history_config()))
		grid.addWidget(QLabel(_('Currency')), 1, 0, Qt.AlignRight)
		self.default_amount_currency = QComboBox()
		self.default_amount_currency.addItems(self.currencies)
		self.default_amount_currency.setCurrentIndex(
			self.default_amount_currency.findText(
				read_config(self.wallet, "default_amount_currency", c["default_amount_currency"])
			)
		)
		def on_default_amount_currency():
			write_config(self.wallet, "default_amount_currency", self.currencies[self.default_amount_currency.currentIndex()])
		self.default_amount_currency.currentIndexChanged.connect(on_default_amount_currency)
		grid.addWidget(self.default_amount_currency, 1, 1)

		# --- group autopay
		gbox = QGroupBox(_("AutoPay"))
		vbox = QVBoxLayout(gbox)
		main_layout.addWidget(gbox)

		# autopay checkbox
		self.cb_autopay = QCheckBox(_("AutoPay - Automatically pay unpaid tips as chaintip message comes in"))
		self.cb_autopay.setChecked(read_config(self.wallet, "autopay", c["default_autopay"]))
		def on_cb_autopay():
			self.cb_autopay_limit.setEnabled(self.cb_autopay.isChecked())
			self.cb_autopay_disallow_default.setEnabled(self.cb_autopay.isChecked())
			write_config(self.wallet, "autopay", self.cb_autopay.isChecked())
			on_cb_autopay_limit()
		self.cb_autopay.stateChanged.connect(on_cb_autopay)
		vbox.addWidget(self.cb_autopay)

		# don't autopay when default amount is used
		self.cb_autopay_disallow_default = QCheckBox(_("Disallow AutoPay when Default Tip Amount is used"))
		self.cb_autopay_disallow_default.setChecked(read_config(self.wallet, "autopay_disallow_default", c["default_autopay_disallow_default"]))
		def on_cb_autopay_disallow_default():
			write_config(self.wallet, "autopay_disallow_default", self.cb_autopay_disallow_default.isChecked())
		self.cb_autopay_disallow_default.stateChanged.connect(on_cb_autopay_disallow_default)
		vbox.addWidget(self.cb_autopay_disallow_default)

		# autopay limit checkbox
		self.cb_autopay_limit = QCheckBox(_("Limit AutoPay Amount"))
		self.cb_autopay_limit.setChecked(read_config(self.wallet, "autopay_use_limit", c["default_autopay_use_limit"]))
		def on_cb_autopay_limit():
			self.autopay_limit_bch_label.setEnabled(self.cb_autopay.isChecked() and self.cb_autopay_limit.isChecked())
			self.autopay_limit_bch.setEnabled(self.cb_autopay.isChecked() and self.cb_autopay_limit.isChecked())
			write_config(self.wallet, "autopay_use_limit", self.cb_autopay_limit.isChecked())
		self.cb_autopay_limit.stateChanged.connect(on_cb_autopay_limit)
		vbox.addWidget(self.cb_autopay_limit)

		# autopay limit (amount)
		hbox = QHBoxLayout()
		vbox.addLayout(hbox)
		self.autopay_limit_bch_label = QLabel(_('AutoPay Limit (BCH)'))
		hbox.addWidget(self.autopay_limit_bch_label, 10, Qt.AlignRight)
		self.autopay_limit_bch = QLineEdit()
		self.autopay_limit_bch.setText(read_config(self.wallet, "autopay_limit_bch", c["default_autopay_limit_bch"]))
		def on_autopay_limit_bch():
			write_config(self.wallet, "autopay_limit_bch", self.autopay_limit_bch.text())
		self.autopay_limit_bch.editingFinished.connect(on_autopay_limit_bch)
		hbox.addWidget(self.autopay_limit_bch, 40)

		# ensure correct enable state
		on_cb_autopay()


		# close button
		cbut = CloseButton(self)
		main_layout.addLayout(Buttons(cbut))
		cbut.setDefault(False)
		cbut.setAutoDefault(False)

	def closeEvent(self, event):
		super().closeEvent(event)
		if event.isAccepted():
			self.setParent(None)
			del self.wallet._chaintipper_settings_window
		self.wallet_ui.reddit.triggerRefreshTips();

	def showEvent(self, event):
		super().showEvent(event)
		# if event.isAccepted():
		# 	self.refresh()
