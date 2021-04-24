from PyQt5 import QtGui
from PyQt5 import QtCore
from PyQt5.QtWidgets import QMessageBox
from PyQt5.QtWidgets import QAction
from PyQt5.QtCore import Qt

import weakref

from electroncash.i18n import _
from electroncash.plugins import BasePlugin, hook
from electroncash_gui.qt.util import destroyed_print_error
from electroncash.util import finalization_print_error
from electroncash_gui.qt.main_window import StatusBarButton
from electroncash.wallet import Abstract_Wallet

from . import ui
from .qresources import qInitResources

from . import fullname

icon_chaintip = QtGui.QIcon(":icons/chaintip.svg")
icon_chaintip_gray = QtGui.QIcon(":icons/chaintip_gray.svg")

# class DisabledChaintipperButton(StatusBarButton):
# 	def __init__(self, wallet, message):
# 		super().__init__(icon_chaintip_gray, fullname, self.show_message)
# 		self.wallet = wallet
# 		self.message = message
# 		self.setToolTip(_("ChainTipper (disabled)"))
# 		self.setStatusTip(_("ChainTipper - Disabled (click to enable)"))

# 	def show_message(self):
# 		QMessageBox.information(Plugin.get_suitable_dialog_window_parent(self.wallet),
# 								_("ChainTipper is disabled"), self.message)

class ChaintipperButton(StatusBarButton):
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

	def __init__(self, plugin, wallet):
		super().__init__(icon_chaintip, fullname, self.toggle_active)

		self.is_active = False

		self.plugin = plugin
		self.wallet = wallet

		self.action_toggle = QAction(_("Active on this wallet"))
		self.action_toggle.setCheckable(True)
		self.action_toggle.triggered.connect(self.toggle_active)

		action_separator1 = QAction(self); action_separator1.setSeparator(True)

		action_wsettings = QAction(_("Wallet-specific Settings..."), self)
		action_wsettings.triggered.connect(self.show_wallet_settings)
		action_settings = QAction(_("Global Settings..."), self)
		action_settings.triggered.connect(self.plugin.show_settings_dialog)
		action_separator2 = QAction(self); action_separator2.setSeparator(True)

		self.addActions([self.action_toggle, action_separator1,
						 action_wsettings, action_settings])

		self.setContextMenuPolicy(Qt.ActionsContextMenu)

		self.update_state()

	def update_state(self):
		self.action_toggle.setChecked(self.is_active)
		if self.is_active:
			self.setIcon(icon_chaintip)
			self.setToolTip(_('ChainTipper is active on this wallet'))
			self.setStatusTip(_('Chaintiper - Active'))
			self.plugin.activate(self.wallet)
		else:
			self.setIcon(icon_chaintip_gray)
			self.setToolTip(_('ChainTipper not active on this wallet'))
			self.setStatusTip(_('Chaintiper - Inactive (click to activate on this wallet)'))
			self.plugin.deactivate(self.wallet)

	def toggle_active(self):
		if self.is_active:
			self.is_active = False
		else:
			self.is_active = True
		self.update_state()

	def show_wallet_settings(self):
		win = getattr(self.wallet, '_chaintipper_settings_window', None)
		if not win:
			win = WalletSettingsDialog(
				ChaintipperButton.get_suitable_dialog_window_parent(self.wallet),
				self.plugin, self.wallet
			)
			self.plugin.widgets.add(win)  # ensures if plugin is unloaded while dialog is up, that the dialog will be killed.
		win.show()
		win.raise_()


class Plugin(BasePlugin):
	electrumcash_qt_gui = None

	def __init__(self, parent, config, name):
		BasePlugin.__init__(self, parent, config, name)

		self.widgets = weakref.WeakSet() # widgets we made, that need to be hidden & deleted when plugin is disabled

		# all this stuff is stored by wallet_name (right?), why not use a class for this and migrate the functions also... much cleaner.
		self.wallet_windows = {}
		self.lw_tabs = {}
		self.lw_tab = {}
		self.previous_tab_index = {}

	def fullname(self):
		return 'ChainTipper'

	def diagnostic_name(self):
		return "ChainTipper"

	def description(self):
		return _("Chaintip auto-tipping bot")

	def on_close(self):
		"""
		BasePlugin callback called when the wallet is disabled among other things.
		"""
		for window in list(self.wallet_windows.values()):
			self.close_wallet(window.wallet)

	@hook
	def update_contact(self, address, new_entry, old_entry):
		self.print_error("update_contact", address, new_entry, old_entry)

	@hook
	def delete_contacts(self, contact_entries):
		self.print_error("delete_contacts", contact_entries)

	@hook
	def init_qt(self, qt_gui):
		"""
		Hook called when a plugin is loaded (or enabled).
		"""
		self.electrumcash_qt_gui = qt_gui
		# We get this multiple times.  Only handle it once, if unhandled.
		if len(self.wallet_windows):
			return

		# These are per-wallet windows.
		for window in self.electrumcash_qt_gui.windows:
			self.load_wallet(window.wallet, window)

	def activate(self, wallet):
		"""
		Will be called by the ChaintipperButton on activation
		"""
		wallet_name = wallet.basename()
		window = self.wallet_windows[wallet_name]
		self.add_ui_for_wallet(wallet_name, window)
		self.refresh_ui_for_wallet(wallet_name)
		self.show_chaintipper_tab(wallet_name)

	def deactivate(self, wallet):
		"""
		Will be called by the ChaintipperButton on deactivation
		"""
		wallet_name = wallet.basename()
		self.show_previous_tab(wallet_name)
		window = self.wallet_windows[wallet_name]
		self.remove_ui_for_wallet(wallet_name, window)
		# self.close_wallet(wallet) # TODO: this might be misuse

	@hook
	def load_wallet(self, wallet, window):
		"""
		Hook called when a wallet is loaded and a window opened for it.
		"""
		wallet_name = window.wallet.basename()
		self.print_error("load_wallet(", wallet_name,")")
		self.wallet_windows[wallet_name] = window
		self.print_error("wallet_windows:", self.wallet_windows)
		self.print_error("wallet loaded")

		# self.add_ui_for_wallet(wallet_name, window)
		# self.refresh_ui_for_wallet(wallet_name)

		# setup chaintipper button
		active = False
		if not active:
			sbmsg = _('ChainTipper disabled, click to enable')
		sbbtn = ChaintipperButton(self, wallet)

		# bit of a dirty hack, to insert our status bar icon (always using index 4, should put us just after the password-changer icon)
		sb = window.statusBar()
		sb.insertPermanentWidget(4, sbbtn)
		self.widgets.add(sbbtn)
		window._chaintipper_button = weakref.ref(sbbtn)

	@hook
	def close_wallet(self, wallet):
		self.print_error("************************ close_wallet")
		wallet_name = wallet.basename()
		window = self.wallet_windows[wallet_name]
		del self.wallet_windows[wallet_name]
		self.remove_ui_for_wallet(wallet_name, window)

	def add_ui_for_wallet(self, wallet_name, window):
		l = ui.LoadRWallet(window, self, wallet_name)
		tab = window.create_list_tab(l)
		self.lw_tabs[wallet_name] = tab
		self.lw_tab[wallet_name] = l

		window.tabs.addTab(tab, icon_chaintip, _('ChainTipper'))

	def remove_ui_for_wallet(self, wallet_name, window):
		wallet_tab = self.lw_tabs.get(wallet_name)
		widget = self.lw_tab.get(wallet_name)
		if wallet_tab is not None:
			if widget and callable(getattr(widget, 'kill_join', None)):
				widget.kill_join()  # kill thread, wait for up to 2.5 seconds for it to exit
			if widget and callable(getattr(widget, 'clean_up', None)):
				widget.clean_up()  # clean up wallet and stop its threads
			del self.lw_tab[wallet_name]
			del self.lw_tabs[wallet_name]
			if wallet_tab:
				i = window.tabs.indexOf(wallet_tab)
				window.tabs.removeTab(i)
				wallet_tab.deleteLater()
				self.print_error("Removed UI for", wallet_name)

	def refresh_ui_for_wallet(self, wallet_name):
		wallet_tab = self.lw_tabs.get(wallet_name)
		if wallet_tab:
			wallet_tab.update()
		wallet_tab = self.lw_tab.get(wallet_name)
		if wallet_tab:
			wallet_tab.update()

	def show_chaintipper_tab(self, wallet_name):
		window = self.wallet_windows[wallet_name]
		wallet_tab = self.lw_tabs.get(wallet_name)
		if wallet_tab:
			self.previous_tab_index[wallet_name] = window.tabs.currentIndex()
			window.tabs.setCurrentIndex(window.tabs.indexOf(wallet_tab))

	def show_previous_tab(self, wallet_name):
		window = self.wallet_windows[wallet_name]
		if wallet_name in self.previous_tab_index:
			window.tabs.setCurrentIndex(self.previous_tab_index[wallet_name])
			del self.previous_tab_index[wallet_name]

	# def switch_to(self, mode, wallet_name, recipient_wallet, time, password):
	# 	window=self.wallet_windows[wallet_name]
	# 	try:
	# 		l = mode(window, self, wallet_name, recipient_wallet,time, password=password)

	# 		tab = window.create_list_tab(l)
	# 		destroyed_print_error(tab)  # track object lifecycle
	# 		finalization_print_error(tab)  # track object lifecycle

	# 		old_tab = self.lw_tabs.get(wallet_name)
	# 		i = window.tabs.indexOf(old_tab)

	# 		self.lw_tabs[wallet_name] = tab
	# 		self.lw_tab[wallet_name] = l
	# 		window.tabs.addTab(tab, self._get_icon(), _('Inter-Wallet Transfer'))
	# 		if old_tab:
	# 			window.tabs.removeTab(i)
	# 			old_tab.searchable_list.deleteLater()
	# 			old_tab.deleteLater()  # Qt (and Python) will proceed to delete this widget
	# 	except Exception as e:
	# 		self.print_error(repr(e))
	# 		return

	def show_settings_dialog(self):
		self.print_error("show_settings_dialog() not implemented")