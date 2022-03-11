from PyQt5 import QtGui
from PyQt5 import QtCore
from PyQt5.QtWidgets import QMessageBox
from PyQt5.QtWidgets import (
	QAction, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QGroupBox, QCheckBox, 
	QStackedLayout, QWidget, QGridLayout, QRadioButton, QDoubleSpinBox, QSpinBox,
	QSizePolicy, QLineEdit
)
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

import traceback
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
from electroncash.util import finalization_print_error, inv_dict, format_time
from electroncash.util import PrintError
from electroncash.wallet import Abstract_Wallet

from .qresources import qInitResources

from . import fullname
from .reddit import Reddit
from .model import TipList, TipListener
from .tiplist import TipListWidget, PersistentTipList, StorageVersionMismatchException
from .util import read_config, write_config, commit_config
from .config import c, amount_config_to_rich_text
from .blockchain_watcher import BlockchainWatcher
from .autopay import AutoPay
from .raintipper import RaintipperInitDialog

icon_chaintip = QtGui.QIcon(":icons/chaintip.svg")
icon_chaintip_gray = QtGui.QIcon(":icons/chaintip_gray.svg")


###################################################################################
#                                                                                 #
#    I8,        8        ,8I          88 88                    88        88 88    #
#    `8b       d8b       d8'          88 88              ,d    88        88 88    #
#     "8,     ,8"8,     ,8"           88 88              88    88        88 88    #
#      Y8     8P Y8     8P ,adPPYYba, 88 88  ,adPPYba, MM88MMM 88        88 88    #
#      `8b   d8' `8b   d8' ""     `Y8 88 88 a8P_____88   88    88        88 88    #
#       `8a a8'   `8a a8'  ,adPPPPP88 88 88 8PP"""""""   88    88        88 88    #
#        `8a8'     `8a8'   88,    ,88 88 88 "8b,   ,aa   88,   Y8a.    .a8P 88    #
#         `8'       `8'    `"8bbdP"Y8 88 88  `"Ybbd8"'   "Y888  `"Y8888Y"'  88    #
#                                                                                 #
#                                                                                 #
###################################################################################

class WalletUI(MessageBoxMixin, PrintError, QWidget):
	"""
	Encapsulates UI for a wallet and associated window.
	Plugin class will instantiate one WalletUI per wallet.
	"""
	def __init__(self, plugin, wallet: Abstract_Wallet, window: ElectrumWindow):
		QWidget.__init__(self, window)
		self.plugin = plugin
		self.window = window
		self.wallet = wallet
		self.wallet_name = self.wallet.basename()

		self.widgets = weakref.WeakSet() # widgets we made, that need to be hidden & deleted when plugin is disabled
		self.wallet_tab = None
		self.tab = None
		self.previous_tab_index = None
		self.reddit = None
		self.tiplist = None

		self.old_debug_stats = ""

		# layout
		self.vbox = vbox = QVBoxLayout()
		vbox.setContentsMargins(0, 0, 0, 0)
		self.setLayout(vbox)

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

	def persistTipList(self):
		if hasattr(self, "tiplist") and isinstance(self.tiplist, PersistentTipList):
			self.tiplist.write_if_dirty(self.wallet.storage)

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

	def activate(self):
		"""
		Will be called by the ChaintipperButton on activation.
		Constructs UI and starts reddit thread
		"""

		# update checker
		self.plugin.runUpdateChecker(self.window)

		# wait for wallet to sync to help avoid spending spent utxos
		self.wallet.wait_until_synchronized()

		# create reddit and ui
		self.reddit = Reddit(self)

		if not self.reddit.login():
			# login fails, deactivate, inform user and open settings dialog
			self.print_error("reddit.login() returned False")
			self.window.show_critical(_("Reddit authentication failed.\n\nDeactivating chaintipper on this wallet.\n\nYou can activate it to try again.\n\n"))
			return False

		else:
			if self.reddit.await_reddit_authorization():
				self.add_ui()

				self.reddit.new_tip.connect(self.tiplist.addTip)
				self.print_error("initializeTipList")
				self.initializeTipList()

				self.print_error("reddit.start_thread()")
				self.reddit.start_thread()
				self.reddit.dathread.finished.connect(self.reddit_thread_finished)

				self.refresh_ui()
				self.show_chaintipper_tab()

				return True
			else:
				self.print_error("reddit.await_reddit_auhtorization() returned False")
				self.window.show_critical(_("Reddit authorization failed.\n\nDeactivating chaintipper on this wallet.\n\nYou can activate it to try again.\n\n"))
				return False



	def deactivate(self):
		"""
		Will be called by the ChaintipperButton on deactivation.
		Deconstructs UI and winds down reddit thread
		"""
		if self.reddit and hasattr(self.reddit, "dathread"):
			self.reddit.dathread.finished.connect(self.reddit_thread_finished)
			self.reddit.quit()
		else:
			self.reddit_thread_finished()

		# write storage
		self.wallet.storage.write()

	def reddit_thread_finished(self):
		self.remove_ui()
		self.show_previous_tab()
		if self.reddit and hasattr(self.reddit, "dathread"):
			try: 
				self.reddit.dathread.finished.disconnect(self.reddit_thread_finished)
			except TypeError as e:
				self.print_error("error disconnecting finished signal: ", e)

		self.sbbtn.transition_finished()

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

	def importError(self, stuff):
		klass, exc, tb = stuff
		self.print_error("import error:", klass, exc)
		traceback.print_tb(tb)
		self.window.show_error(_("Import aborted with error: {klass} {exc}. Please report (more info in output)").format(klass=klass, exc=exc))

	def importTipsFromReddit(self):
		choice = self.msg_box(
			icon = QMessageBox.Question,
			parent = self.window,
			title = _("Cannot load tips from wallet file"),
			rich_text = True,
			text = "".join([
				"<h3>", _("No valid tip data found in storage"), "</h3>",
				_("Either there are no tips stored in your wallet file (yet) or the storage version is too old"), "<br><br>",
				_("You can 'import' tips (i.e. read inbox items authored by u/chaintip) from reddit... either all available items, 10 days worth of items or only items that are currently marked 'unread'."), "<br><br>",
				_("After this initial import, new items coming into your inbox will be automatically read and digested into the list of tips according to their meaning."), "<br><br>"
			]),
			buttons = (_("Import all available"), _("Import 10 days worth"), _("Import nothing")),
			defaultButton = _("Import 10 days worth"),
			escapeButton = _("Import nothing"),
		)
		if choice in (0, 1): # import messages from reddit
			days = (-2, 10)[choice]
			#self.reddit.triggerMarkChaintipMessagesUnread(days)
			#self.reddit.triggerImport(days)
			
			# import...
			try:
				dialog = WaitingDialog(self.window, "importing from Reddit...", lambda: self.reddit.doImport(days), auto_exec=True, on_error=self.importError)
			except Exception as e:
				traceback.print_exc()
				traceback.print_stack()

	def importRecentTipsFromReddit(self):
		dates = []
		for tip in self.tiplist.tips.values():
			if hasattr(tip, "chaintip_message_created_utc"):
				dates.append(int(tip.chaintip_message_created_utc))
		if len(dates) > 0:
			dates = sorted(dates)
			self.print_error(f"importRecentTipsFromReddit(): latest tip date: {dates[-1]} = {format_time(dates[-1])}, importing...")
			# import...
			try:
				dialog = WaitingDialog(self.window, _("importing from Reddit (starting {d})...").format(d=format_time(dates[-1])), lambda: self.reddit.doImport(-3, dates[-1]), auto_exec=True, on_error=self.importError)
			except Exception as e:
				traceback.print_exc()
				traceback.print_stack()

	def initializeTipList(self):
		try:
			self.tiplist.read(self.wallet.storage)
			self.importRecentTipsFromReddit()
		except StorageVersionMismatchException as e:
			self.print_error("error loading tips from wallet file: ", e)
			self.importTipsFromReddit()

	def add_ui(self):
		"""construct TipList, and a tab with tiplist widget and add it to window"""
		self.tiplist = PersistentTipList(self)
		self.autopay = AutoPay(self.wallet, self.tiplist)
		self.reddit.addWorker(self.autopay)
		self.blockchain_watcher = BlockchainWatcher(self.wallet, self.tiplist)
		self.tiplist_widget = TipListWidget(self, self.window, self.wallet, self.tiplist, self.reddit)
		self.vbox.addWidget(self.tiplist_widget)

		self.tab = self.window.create_list_tab(self)
		self.window.tabs.addTab(self.tab, icon_chaintip, _('ChainTipper'))

	def remove_ui(self):
		"""deconstruct the UI created in add_ui(), leaving self.vbox"""
		if hasattr(self, "autopay") and self.autopay:
			self.reddit.removeWorker(self.autopay)
			del self.autopay
		if hasattr(self, "blockchain_watcher") and self.blockchain_watcher:
			del self.blockchain_watcher
		if self.vbox:
			self.vbox.removeWidget(self.tiplist_widget)
		if hasattr(self, "tiplist") and self.tiplist:
			del self.tiplist
		if hasattr(self, "tab") and self.tab:
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

	def show_raintipper_init_dialog(self):
		raintipper_init_dialog = getattr(self.wallet, '_raintipper_init_dialog', None)
		if not raintipper_init_dialog:
			#win = WalletSettingsDialog(self, ChaintipperButton.get_suitable_dialog_window_parent(self.wallet))
			raintipper_init_dialog = RaintipperInitDialog(self, self.window)
			self.widgets.add(self.window)  # adding to widgets list ensures if plugin is unloaded while dialog is up, that the dialog will be killed.
		raintipper_init_dialog.show()
		raintipper_init_dialog.raise_()


########################################################################
#                                                                      #
#    88888888ba                                                        #
#    88      "8b               ,d      ,d                              #
#    88      ,8P               88      88                              #
#    88aaaaaa8P' 88       88 MM88MMM MM88MMM ,adPPYba,  8b,dPPYba,     #
#    88""""""8b, 88       88   88      88   a8"     "8a 88P'   `"8a    #
#    88      `8b 88       88   88      88   8b       d8 88       88    #
#    88      a8P "8a,   ,a88   88,     88,  "8a,   ,a8" 88       88    #
#    88888888P"   `"YbbdP'Y8   "Y888   "Y888 `"YbbdP"'  88       88    #
#                                                                      #
#                                                                      #
########################################################################

class ChaintipperButton(StatusBarButton, PrintError):

	def __init__(self, wallet_ui):
		super().__init__(icon_chaintip, fullname, self.toggle_active)

		self.is_active = False

		self.wallet_ui = wallet_ui

		self.action_toggle = QAction(_("Active on this wallet"))
		self.action_toggle.setCheckable(True)
		self.action_toggle.triggered.connect(self.toggle_active)

		action_separator1 = QAction(self); 
		action_separator1.setSeparator(True)

		action_wsettings = QAction(_("Wallet-specific Settings..."), self)
		action_wsettings.triggered.connect(self.wallet_ui.show_wallet_settings)

		action_settings = QAction(_("Forget Reddit Authorization (e.g. to switch reddit account)"), self)
		action_settings.triggered.connect(self.disconnect_reddit)

		action_separator2 = QAction(self); 
		action_separator2.setSeparator(True)

		show_monikers = QAction(_("Show Amount Monikers"), self)
		show_monikers.triggered.connect(self.showMonikers)

		self.addActions([
			self.action_toggle, 
			action_separator1,
			action_wsettings,
			action_settings,
			show_monikers
		])

		if read_config(self.wallet_ui.wallet, "enable_raintipper", False):
			action_raintipper_init = QAction(_("Initiate a RainTipper instance..."), self)
			action_raintipper_init.triggered.connect(self.wallet_ui.show_raintipper_init_dialog)
			action_separator3 = QAction(self); 
			action_separator3.setSeparator(True)
			self.addActions([action_separator3, action_raintipper_init])

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
		else:
			self.setIcon(icon_chaintip_gray)
			self.setToolTip(_('ChainTipper - not active on wallet "{wallet_name}"').format(wallet_name=self.wallet_ui.wallet_name))
			self.setStatusTip(_('ChainTipper - Inactive (click to activate on wallet "{wallet_name}")').format(wallet_name=self.wallet_ui.wallet_name))
		
	def toggle_active(self):
		self.set_active(not self.is_active)

	def set_active(self, active):
		self.setDisabled(True)
		QApplication.processEvents()
		if self.is_active != active:
			self.is_active = active
			if self.is_active:
				if not self.wallet_ui.activate():
					self.is_active = False
				self.transition_finished()
			else:
				self.wallet_ui.deactivate()
				# transition_finished called by wallet_ui.reddit_thread_finished

	def transition_finished(self):
		self.setDisabled(False)
		self.update_state()


	def disconnect_reddit(self):
		self.wallet_ui.reddit.disconnect()
		self.set_active(False)
		self.transition_finished()



#####################################################################################
#                                                                                   #
#     ad88888ba                             88                                      #
#    d8"     "8b              ,d      ,d    ""                                      #
#    Y8,                      88      88                                            #
#    `Y8aaaaa,    ,adPPYba, MM88MMM MM88MMM 88 8b,dPPYba,   ,adPPYb,d8 ,adPPYba,    #
#      `"""""8b, a8P_____88   88      88    88 88P'   `"8a a8"    `Y88 I8[    ""    #
#            `8b 8PP"""""""   88      88    88 88       88 8b       88  `"Y8ba,     #
#    Y8a     a8P "8b,   ,aa   88,     88,   88 88       88 "8a,   ,d88 aa    ]8I    #
#     "Y88888P"   `"Ybbd8"'   "Y888   "Y888 88 88       88  `"YbbdP"Y8 `"YbbdP"'    #
#                                                           aa,    ,88              #
#                                                            "Y8bbdP"               #
#####################################################################################

class WalletSettingsDialog(WindowModalDialog, PrintError, MessageBoxMixin):
	"""Dialog for wallet-specific settings"""

	def __init__(self, wallet_ui, parent):
		super().__init__(parent=parent, title=_("ChainTipper - Wallet-specific Settings"))
		self.setWindowIcon(icon_chaintip)
		self.wallet_ui = wallet_ui
		self.wallet = self.wallet_ui.wallet # TODO: remove and refactor to increase code clarity?

		# what is this crap? commenting it out
		# self.idx2confkey = dict()   # int -> 'normal', 'consolidate', etc..
		# self.confkey2idx = dict()   # str 'normal', 'consolidate', etc -> int

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
		self.cb_activate_on_open.setChecked(read_config(self.wallet, "activate_on_wallet_open"))
		def on_cb_activate_on_open():
			write_config(self.wallet, "activate_on_wallet_open", self.cb_activate_on_open.isChecked())
		self.cb_activate_on_open.stateChanged.connect(on_cb_activate_on_open)
		grid.addWidget(self.cb_activate_on_open)

		# mark read digested
		self.cb_mark_read_digested_tips = QCheckBox(_("Keep my inbox clean by marking messages/comments as read when they are digested"))
		self.cb_mark_read_digested_tips.setChecked(read_config(self.wallet, "mark_read_digested_tips"))
		def on_cb_mark_read_digested_tips():
			write_config(self.wallet, "mark_read_digested_tips", self.cb_mark_read_digested_tips.isChecked())
		self.cb_mark_read_digested_tips.stateChanged.connect(on_cb_mark_read_digested_tips)
		grid.addWidget(self.cb_mark_read_digested_tips)

		# --- group Default Tip Amount ------------------------------------------------------------------------------------------

		main_layout.addStretch(1)

		gbox = QGroupBox(_("Default Tip Amount (used when amount parsing fails)"))
		grid = QGridLayout(gbox)
		main_layout.addWidget(gbox)

		# amount
		grid.addWidget(QLabel(_('Amount')), 0, 1, Qt.AlignRight)
		self.default_amount = QLineEdit()
		self.default_amount.setText(read_config(self.wallet, "default_amount"))
		def on_default_amount():
			try:
				self.default_amount.setText(str(decimal.Decimal(self.default_amount.text())))
			except decimal.InvalidOperation as e:
				self.show_error(_("Cannot parse {string} as decimal number. Please try again.").format(string=self.default_amount.text()))
				self.default_amount.setText(read_config(self.wallet, "default_amount"))
			write_config(self.wallet, "default_amount", self.default_amount.text())
		self.default_amount.editingFinished.connect(on_default_amount)
		grid.addWidget(self.default_amount, 0, 2)

		# currency
		self.currencies = sorted(self.wallet_ui.window.fx.get_currencies(self.wallet_ui.window.fx.get_history_config()))
		grid.addWidget(QLabel(_('Currency')), 1, 1, Qt.AlignRight)
		self.default_amount_currency = QComboBox()
		self.default_amount_currency.addItems(self.currencies)
		self.default_amount_currency.setCurrentIndex(
			self.default_amount_currency.findText(
				read_config(self.wallet, "default_amount_currency")
			)
		)
		def on_default_amount_currency():
			write_config(self.wallet, "default_amount_currency", self.currencies[self.default_amount_currency.currentIndex()])
		self.default_amount_currency.currentIndexChanged.connect(on_default_amount_currency)
		grid.addWidget(self.default_amount_currency, 1, 2)


		# --- group Linked Default Tip Amount ----------------------------------------------------------------------------------

		main_layout.addStretch(1)

		self.gbox_linked_amount = QGroupBox(_("Special Linked Default Tip Amount (used when amount parsing fails and recipient has linked an address)"))
		self.gbox_linked_amount.setCheckable(True)
		self.gbox_linked_amount.setChecked(read_config(self.wallet, "use_linked_amount"))
		grid = QGridLayout(self.gbox_linked_amount)
		main_layout.addWidget(self.gbox_linked_amount)
		def on_gbox_linked_amount():
			write_config(self.wallet, "use_linked_amount", self.gbox_linked_amount.isChecked())
		self.gbox_linked_amount.toggled.connect(on_gbox_linked_amount)

		# amount
		grid.addWidget(QLabel(_('Amount')), 0, 1, Qt.AlignRight)
		self.default_linked_amount = QLineEdit()
		self.default_linked_amount.setText(read_config(self.wallet, "default_linked_amount"))
		def on_default_linked_amount():
			try:
				self.default_linked_amount.setText(str(decimal.Decimal(self.default_linked_amount.text())))
			except decimal.InvalidOperation as e:
				self.show_error(_("Cannot parse {string} as decimal number. Please try again.").format(string=self.default_linked_amount.text()))
				self.default_linked_amount.setText(read_config(self.wallet, "default_linked_amount"))
			write_config(self.wallet, "default_linked_amount", self.default_linked_amount.text())
		self.default_linked_amount.editingFinished.connect(on_default_linked_amount)
		grid.addWidget(self.default_linked_amount, 0, 2)

		# currency
		self.currencies = sorted(self.wallet_ui.window.fx.get_currencies(self.wallet_ui.window.fx.get_history_config()))
		grid.addWidget(QLabel(_('Currency')), 1, 1, Qt.AlignRight)
		self.default_linked_amount_currency = QComboBox()
		self.default_linked_amount_currency.addItems(self.currencies)
		self.default_linked_amount_currency.setCurrentIndex(
			self.default_linked_amount_currency.findText(
				read_config(self.wallet, "default_linked_amount_currency")
			)
		)
		def on_default_linked_amount_currency():
			write_config(self.wallet, "default_linked_amount_currency", self.currencies[self.default_linked_amount_currency.currentIndex()])
		self.default_linked_amount_currency.currentIndexChanged.connect(on_default_linked_amount_currency)
		grid.addWidget(self.default_linked_amount_currency, 1, 2)

		# set amount to 0 for stealth tips 
		self.cb_set_amount_to_zero_for_stealth_tips = QCheckBox()
		self.cb_set_amount_to_zero_for_stealth_tips.setChecked(read_config(self.wallet, "set_amount_to_zero_for_stealth_tips"))
		def on_cb_set_amount_to_zero_for_stealth_tips():
			write_config(self.wallet, "set_amount_to_zero_for_stealth_tips", self.cb_set_amount_to_zero_for_stealth_tips.isChecked())
		self.cb_set_amount_to_zero_for_stealth_tips.stateChanged.connect(on_cb_set_amount_to_zero_for_stealth_tips)
		grid.addWidget(self.cb_set_amount_to_zero_for_stealth_tips, 2, 1, Qt.AlignRight)
		grid.addWidget(QLabel(_("Set amount to 0 for stealth tips")), 2, 2)


		# --- group autopay ---------------------------------------------------------------------------------------------------

		main_layout.addStretch(1)

		self.gbox_autopay = QGroupBox(_("AutoPay - Automatically pay unpaid tips"))
		self.gbox_autopay.setCheckable(True)
		self.gbox_autopay.setChecked(read_config(self.wallet, "autopay"))
		vbox = QVBoxLayout(self.gbox_autopay)
		main_layout.addWidget(self.gbox_autopay)
		def on_gbox_autopay():
			write_config(self.wallet, "autopay", self.gbox_autopay.isChecked())
			#on_cb_autopay_limit()
		self.gbox_autopay.toggled.connect(on_gbox_autopay)

		# disallow autopay when default amount is used
		self.cb_autopay_disallow_default = QCheckBox(_("Disallow AutoPay when Default Tip Amount is used"))
		self.cb_autopay_disallow_default.setChecked(read_config(self.wallet, "autopay_disallow_default"))
		def on_cb_autopay_disallow_default():
			write_config(self.wallet, "autopay_disallow_default", self.cb_autopay_disallow_default.isChecked())
		self.cb_autopay_disallow_default.stateChanged.connect(on_cb_autopay_disallow_default)
		vbox.addWidget(self.cb_autopay_disallow_default)

		# autopay limit checkbox
		self.cb_autopay_limit = QCheckBox(_("Limit AutoPay Amount"))
		self.cb_autopay_limit.setChecked(read_config(self.wallet, "autopay_use_limit"))
		def on_cb_autopay_limit():
			self.autopay_limit_bch_label.setEnabled(self.gbox_autopay.isChecked() and self.cb_autopay_limit.isChecked())
			self.autopay_limit_bch.setEnabled(self.gbox_autopay.isChecked() and self.cb_autopay_limit.isChecked())
			write_config(self.wallet, "autopay_use_limit", self.cb_autopay_limit.isChecked())
		self.cb_autopay_limit.stateChanged.connect(on_cb_autopay_limit)
		vbox.addWidget(self.cb_autopay_limit)

		# autopay limit (amount)
		hbox = QHBoxLayout()
		vbox.addLayout(hbox)
		self.autopay_limit_bch_label = QLabel(_('AutoPay Limit (BCH per Tip)'))
		hbox.addWidget(self.autopay_limit_bch_label, 10, Qt.AlignRight)
		self.autopay_limit_bch = QLineEdit()
		self.autopay_limit_bch.setText(read_config(self.wallet, "autopay_limit_bch"))
		def on_autopay_limit_bch():
			write_config(self.wallet, "autopay_limit_bch", self.autopay_limit_bch.text())
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
			self.wallet_ui.reddit.triggerRefreshTipAmounts() 

	def showEvent(self, event):
		super().showEvent(event)
		# if event.isAccepted():
		# 	self.refresh()
