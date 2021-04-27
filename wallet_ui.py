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
			self.print_error("reddit login failed")
			self.window.show_critical(_("Reddit authentication failed.\nMost likely reason are invalid credentials. Will open settings so you can supply correct credentials."))
			if self.sbbtn:
				self.sbbtn.toggle_active() # abort activation and toggle back to inactive
				self.show_wallet_settings()
		else:
			self.reddit_thread = QtCore.QThread()
			self.reddit.moveToThread(self.reddit_thread)
			self.reddit_thread.started.connect(self.reddit.run)
			self.reddit.new_tip.connect(self.tiplist.dispatchNewTip)
			self.reddit_thread.start()

			# So that we get told about when new coins come in, and the UI updates itself
			if hasattr(self.window, 'history_updated_signal'):
				self.window.history_updated_signal.connect(self.tiplist_widget.checkPaymentStatus)

	def activate(self):
		"""
		Will be called by the ChaintipperButton on activation.
		Constructs UI and starts reddit thread
		"""
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
		if self.reddit_thread:
			self.reddit_thread.quit()
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
			# win = WalletSettingsDialog(self, ChaintipperButton.get_suitable_dialog_window_parent(self.wallet))
			self.widgets.add(self.wallet_ui.window)  # adding to widgets list ensures if plugin is unloaded while dialog is up, that the dialog will be killed.
		win.show()
		win.raise_()

	def read_config(self, key: str, default=None):
		"""convenience function to write to wallet storage prefixing key with 'chaintipper_'"""
		key = "chaintipper_" + key
		v = self.wallet.storage.get(key)
		if v is None:
			v = default
			self.write_config(key, v)
		return v

	def write_config(self, key: str, value):
		"""convenience to read from wallet storage prefixing key with 'chaintipper_'"""
		key = "chaintipper_" + key
		self.wallet.storage.put(key, value)


class ChaintipperButton(StatusBarButton):
	"""
	ChainTipper Button for tray. 
	Manages (de-)activation of Chaintipper and has a menu for gloabl and wallet-specific settings
	"""
	@classmethod
	def window_for_wallet(cls, wallet):
		''' Convenience: Given a wallet instance, derefernces the weak_window
		attribute of the wallet and returns a strong reference to the window.
		May return None if the window is gone (deallocated).  '''
		assert isinstance(wallet, Abstract_Wallet)
		return (wallet.weak_window and wallet.weak_window()) or None

	@classmethod
	def get_suitable_dialog_window_parent(cls, wallet_or_window):
		''' Convenience: Given a wallet or a window instance, return a suitable
		'top level window' parent to use for dialog boxes. '''
		if isinstance(wallet_or_window, Abstract_Wallet):
			wallet = wallet_or_window
			window = cls.window_for_wallet(wallet)
			return (window and window.top_level_window()) or None
		elif isinstance(wallet_or_window, ElectrumWindow):
			window = wallet_or_window
			return window.top_level_window()
		else:
			raise TypeError(f"Expected a wallet or a window instance, instead got {type(wallet_or_window)}")

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
		action_settings = QAction(_("Global Settings..."), self)
#		action_settings.triggered.connect(self.wallet_ui.plugin.show_settings_dialog)
		action_separator2 = QAction(self); action_separator2.setSeparator(True)

		self.addActions([self.action_toggle, action_separator1,
						 action_wsettings, action_settings])

		self.setContextMenuPolicy(Qt.ActionsContextMenu)

		self.update_state()

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


class WalletSettingsDialog(WindowModalDialog, PrintError):
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
		self.wallet._cashfusion_settings_window = self

		main_layout = QVBoxLayout(self)

		# reddit credentials
		gbox = QGroupBox(_("Reddit Credentials"))
		grid = QGridLayout(gbox)
		# grid.setColumnStretch(0, 1)
		# grid.setColumnStretch(1, 3)
		main_layout.addWidget(gbox)

		# reddit username
		grid.addWidget(QLabel(_('Username')), 0, 0, Qt.AlignRight)
		self.reddit_username = QLineEdit()
		self.reddit_username.setText(self.wallet_ui.read_config("reddit_username"))
		def on_reddit_username():
			self.wallet_ui.write_config("reddit_username", self.reddit_username.text())
		self.reddit_username.editingFinished.connect(on_reddit_username)
		grid.addWidget(self.reddit_username, 0, 1)

		# reddit password
		grid.addWidget(QLabel(_('Password')), 1, 0, Qt.AlignRight)
		self.reddit_password = QLineEdit()
		self.reddit_password.setEchoMode(QLineEdit.Password)
		self.reddit_password.setText(self.wallet_ui.read_config("reddit_password"))
		def on_reddit_password():
			self.wallet_ui.write_config("reddit_password", self.reddit_password.text())
		self.reddit_password.editingFinished.connect(on_reddit_password)
		grid.addWidget(self.reddit_password, 1, 1)


		# close button
		cbut = CloseButton(self)
		main_layout.addLayout(Buttons(cbut))
		cbut.setDefault(False)
		cbut.setAutoDefault(False)

		self.refresh()

	def refresh(self):
		return
		# eligible, ineligible, sum_value, has_unconfirmed, has_coinbase = select_coins(self.wallet)

		# select_type, select_amount = self.conf.selector

		# edit_widgets = [self.amt_selector_size, self.sb_selector_fraction, self.sb_selector_count, self.sb_queued_autofuse,
		# 				self.cb_autofuse_only_all_confirmed, self.combo_self_fuse, self.stacked_layout, self.mode_cb,
		# 				self.cb_coinbase]
		# try:
		# 	for w in edit_widgets:
		# 		# Block spurious editingFinished signals and valueChanged signals as
		# 		# we modify the state and focus of widgets programatically below.
		# 		# On macOS not doing this led to a very strange/spazzy UI.
		# 		w.blockSignals(True)

		# 	self.cb_coinbase.setChecked(self.conf.autofuse_coinbase)
		# 	if not self.gb_coinbase.isVisible():
		# 		cb_latch = self.conf.coinbase_seen_latch
		# 		if cb_latch or self.cb_coinbase.isChecked() or has_coinbase:
		# 			if not cb_latch:
		# 				# Once latched to true, this UI element will forever be
		# 				# visible for this wallet.  It means the wallet is a miner's
		# 				# wallet and they care about coinbase coins.
		# 				self.conf.coinbase_seen_latch = True
		# 			self.gb_coinbase.setHidden(False)
		# 		del cb_latch

		# 	is_custom_page = self._maybe_switch_page()

		# 	idx = 0
		# 	if self.conf.self_fuse_players > 1:
		# 		idx = 1
		# 	self.combo_self_fuse.setCurrentIndex(idx)
		# 	del idx

		# 	if is_custom_page:
		# 		self.amt_selector_size.setEnabled(select_type == 'size')
		# 		self.sb_selector_count.setEnabled(select_type == 'count')
		# 		self.sb_selector_fraction.setEnabled(select_type == 'fraction')
		# 		if select_type == 'size':
		# 			self.radio_select_size.setChecked(True)
		# 			sel_size = select_amount
		# 			if sum_value > 0:
		# 				sel_fraction = min(COIN_FRACTION_FUDGE_FACTOR * select_amount / sum_value, 1.)
		# 			else:
		# 				sel_fraction = 1.
		# 		elif select_type == 'count':
		# 			self.radio_select_count.setChecked(True)
		# 			sel_size = max(sum_value / max(select_amount, 1), 10000)
		# 			sel_fraction = COIN_FRACTION_FUDGE_FACTOR / max(select_amount, 1)
		# 		elif select_type == 'fraction':
		# 			self.radio_select_fraction.setChecked(True)
		# 			sel_size = max(sum_value * select_amount / COIN_FRACTION_FUDGE_FACTOR, 10000)
		# 			sel_fraction = select_amount
		# 		else:
		# 			self.conf.selector = None
		# 			return self.refresh()
		# 		sel_count = COIN_FRACTION_FUDGE_FACTOR / max(sel_fraction, 0.001)
		# 		self.amt_selector_size.setAmount(round(sel_size))
		# 		self.sb_selector_fraction.setValue(max(min(sel_fraction, 1.0), 0.001) * 100.0)
		# 		self.sb_selector_count.setValue(sel_count)
		# 		try: self.sb_queued_autofuse.setValue(self.conf.queued_autofuse)
		# 		except (TypeError, ValueError): pass  # should never happen but paranoia pays off in the long-term
		# 		conf_only = self.conf.autofuse_confirmed_only
		# 		self.cb_autofuse_only_all_confirmed.setChecked(conf_only)
		# 		self.l_warn_selection.setVisible(sel_fraction > 0.2 and (not conf_only or self.sb_queued_autofuse.value() > 1))
		# finally:
		# 	# re-enable signals
		# 	for w in edit_widgets: w.blockSignals(False)



	def closeEvent(self, event):
		super().closeEvent(event)
		if event.isAccepted():
			self.setParent(None)
			del self.wallet._cashfusion_settings_window

	def showEvent(self, event):
		super().showEvent(event)
		if event.isAccepted():
			self.refresh()