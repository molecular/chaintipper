import weakref

from PyQt5 import QtGui
from PyQt5 import QtCore
from PyQt5.QtWidgets import QMessageBox
from PyQt5.QtWidgets import (
	QAction, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QGroupBox, QCheckBox, 
	QStackedLayout, QWidget, QGridLayout, QRadioButton, QDoubleSpinBox, QSpinBox,
	QSizePolicy, QLineEdit
)
from PyQt5.QtCore import Qt, QObject, pyqtSignal
from PyQt5.QtWidgets import QApplication, QTreeWidgetItem, QAbstractItemView, QMenu, QVBoxLayout

from electroncash.i18n import _
from electroncash_gui.qt import ElectrumWindow
from electroncash_gui.qt.util import webopen, MessageBoxMixin, MyTreeWidget
from electroncash_gui.qt.util import (
	PrintError,
	Buttons, CancelButton, CloseButton, OkButton,
	WindowModalDialog
)

from .util import read_config, write_config, commit_config
from .config import c

from .reddit import Reddit, RedditWorker
from . import praw

icon_chaintip = QtGui.QIcon(":icons/chaintip.svg")

#######################################################################################################
#                                                                                                     #
#    88888888ba             88                    88                                                  #
#    88      "8b            ""              ,d    ""                                                  #
#    88      ,8P                            88                                                        #
#    88aaaaaa8P' ,adPPYYba, 88 8b,dPPYba, MM88MMM 88 8b,dPPYba,  8b,dPPYba,   ,adPPYba, 8b,dPPYba,    #
#    88""""88'   ""     `Y8 88 88P'   `"8a  88    88 88P'    "8a 88P'    "8a a8P_____88 88P'   "Y8    #
#    88    `8b   ,adPPPPP88 88 88       88  88    88 88       d8 88       d8 8PP""""""" 88            #
#    88     `8b  88,    ,88 88 88       88  88,   88 88b,   ,a8" 88b,   ,a8" "8b,   ,aa 88            #
#    88      `8b `"8bbdP"Y8 88 88       88  "Y888 88 88`YbbdP"'  88`YbbdP"'   `"Ybbd8"' 88            #
#                                                    88          88                                   #
#                                                    88          88                                   #
#######################################################################################################

class Raintipper(RedditWorker, QWidget):
	"""Encapsulates on rain-tipping session instance"""
	root_object_located = pyqtSignal(object)
#	new_raintip = pyqtSignal(Tip)

	def __init__(self, wallet_ui):
		RedditWorker.__init__(self)
		QWidget.__init__(self)
		self.wallet_ui = wallet_ui
		self.reddit = self.wallet_ui.reddit
		self.window = self.wallet_ui.window
		self.stage = 'init'

		self.tab = None
		self.previous_tab = None

		self.print_error(f"Raintipper instantiated with reddit {self.reddit}")

		# signal for Raintipper.do_work() to inform about located root object

	def locateRootObject(self, s: str):
		self.stage = 'locate_root_object'
		self.root_object_text = s
		self.desired_interval_secs = 0

	def createTab(self):
		# layout
		self.vbox = vbox = QVBoxLayout()
		vbox.setContentsMargins(0, 0, 0, 0)
		self.setLayout(vbox)

		# raintip_list
		self.raintip_list = RaintipList()

		# add raintip_list_widget
		self.raintip_list_widget = RaintipListWidget(self.wallet_ui, self.window, self.raintip_list, self.reddit)
		self.vbox.addWidget(self.raintip_list_widget)

		# register raintip_list_widget as RaintipListener to raintip_list
		self.raintip_list.registerRaintipListener(self.raintip_list_widget)

		# create tab
		if self.tab:
			self.destroyTab()
		self.tab = self.window.create_list_tab(self)
		self.window.tabs.addTab(self.tab, icon_chaintip, 'Rain_' + self.root_object.id)

		# tell worker to start collecting
		self.stage = 'collect'

	def remove_ui(self):
		"""deconstruct the UI created in add_ui(), leaving self.vbox"""
		if hasattr(self, "tab") and self.tab:
			self.window.tabs.removeTab(self.window.tabs.indexOf(self.tab))
			#self.tab.deleteLater()
		self.tab = None


	def destroyTab(self):
		if hasattr(self, "raintip_list_widget") and self.raintip_list_widget:
			self.raintip_list.unregisterRaintipListener(self.raintip_list_widget)
			del self.raintip_list_widget
		if hasattr(self, "raintip_list") and self.raintip_list:
			del self.raintip_list
		if self.tab:
			self.window.tabs.removeTab(self.window.tabs.indexOf(self.tab))
		self.tab = None

	def show_tab(self):
		"""switch main window to our tab"""
		if self.tab:
			self.previous_tab_index = self.window.tabs.currentIndex()
			self.window.tabs.setCurrentIndex(self.window.tabs.indexOf(self.tab))

	# def show_previous_tab(self):
	# 	"""switch main window back to tab selected when show_chaintipper_tab() was called"""
	# 	self.print_error("previous tab index:", self.previous_tab_index)
	# 	if self.previous_tab_index != None:
	# 		self.window.tabs.setCurrentIndex(self.previous_tab_index)
	# 		self.previous_tab_index = None

	# RedditWorker override (runs in reddit thread)
	def do_work(self):
		"""called periodically by reddit thread. Multithreading caveats apply, specially when communicating with gui threads"""

		self.print_error("Raintipper.do_work() called, stage: ", self.stage)

		if self.stage == 'locate_root_object':
			self.print_error(f"looking up root object for '{self.root_object_text}'")						
			o = None

			# look for a Comment by url
			try:
				o = self.reddit.reddit.comment(url=self.root_object_text)
			except Exception as e: o = None

			# look for a Submission by url
			if not o: 
				try:
					o = self.reddit.reddit.submission(url=self.root_object_text)
				except Exception as e: o = None

			# signal found object (or "<not found>")
			if o:
				self.print_error("found reddit object", o, "of type", type(o))
				self.root_object = o
				self.root_object_located.emit(o)
				self.stage = 'root object found'
			else:
				self.root_object_located.emit("<not found>")


		elif self.stage == 'collect':

			# after initial collect, slow down worker
			self.desired_interval_secs = 15

			# collect
			self.collect()

	def collect(self, o=None):
		#self.print_error(f"collecting o={o}")

		if o == None: # start at self.root_object
			o = self.root_object

		# create Raintip based on comment
		elif type(o) == praw.models.Comment:
			existing_raintip = self.raintip_list.getRaintipByID(o.id)
			if existing_raintip:
				self.print_error("updating existing raintip", existing_raintip)
				existing_raintip.update()
			else:
				raintip = Raintip(o, self.raintip_list)
				self.print_error("collected new raintip", raintip)

		# recurse through children
		comment_forest = None
		if type(o) == praw.models.Submission:
			comment_forest = o.comments
		elif type(o) == praw.models.Comment:
			comment_forest = o.replies

		for comment in comment_forest:
			self.collect(comment)


#####################################################################
#                                                                   #
#    88888888ba             88                    88                #
#    88      "8b            ""              ,d    ""                #
#    88      ,8P                            88                      #
#    88aaaaaa8P' ,adPPYYba, 88 8b,dPPYba, MM88MMM 88 8b,dPPYba,     #
#    88""""88'   ""     `Y8 88 88P'   `"8a  88    88 88P'    "8a    #
#    88    `8b   ,adPPPPP88 88 88       88  88    88 88       d8    #
#    88     `8b  88,    ,88 88 88       88  88,   88 88b,   ,a8"    #
#    88      `8b `"8bbdP"Y8 88 88       88  "Y888 88 88`YbbdP"'     #
#                                                    88             #
#                                                    88             #
#####################################################################

class Raintip(PrintError):
	"""constitutes a Raintip based on a reddit comment"""

	def __init__(self, comment: praw.models.Comment, raintiplist):
		self.comment = comment
		self.raintiplist_weakref = weakref.ref(raintiplist)
		self.add()

	def __str__(self):
		return f"Raintip {self.comment.id}"

	def getID(self):
		return self.comment.id

	def add(self):
		if self.raintiplist_weakref():
			self.raintiplist_weakref().addRaintip(self)
		else:
			self.print_error("weakref to raintiplist broken, can't add raintip", self)


	def update(self):
		if self.raintiplist_weakref():
			self.raintiplist_weakref().updateRaintip(self)
		else:
			self.print_error("weakref to raintiplist broken, can't update raintip", self)

	def remove(self):
		if self.raintiplist_weakref():
			self.raintiplist_weakref().removeRaintip(self)
		else:
			self.print_error("weakref to raintiplist broken, can't remove raintip", self)

######################################################################################################
#                                                                                                    #
#    88888888ba             88                    88             88          88                      #
#    88      "8b            ""              ,d    ""             88          ""             ,d       #
#    88      ,8P                            88                   88                         88       #
#    88aaaaaa8P' ,adPPYYba, 88 8b,dPPYba, MM88MMM 88 8b,dPPYba,  88          88 ,adPPYba, MM88MMM    #
#    88""""88'   ""     `Y8 88 88P'   `"8a  88    88 88P'    "8a 88          88 I8[    ""   88       #
#    88    `8b   ,adPPPPP88 88 88       88  88    88 88       d8 88          88  `"Y8ba,    88       #
#    88     `8b  88,    ,88 88 88       88  88,   88 88b,   ,a8" 88          88 aa    ]8I   88,      #
#    88      `8b `"8bbdP"Y8 88 88       88  "Y888 88 88`YbbdP"'  88888888888 88 `"YbbdP"'   "Y888    #
#                                                    88                                              #
#                                                    88                                              #
######################################################################################################

class RaintipList(PrintError, QObject):
	update_signal = pyqtSignal() # shouldn't these be instance variables?
	added_signal = pyqtSignal()

	def __init__(self):
		QObject.__init__(self)

		self.raintip_listeners = []
		self.raintips = {} # Raintip instances by their getID()

	def addRaintip(self, raintip: Raintip):
		if raintip.getID() in self.raintips.keys():
			raise("duplicate raintip ID")
		else:
			self.raintips[raintip.getID()] = raintip
			self.print_error(f"RaintipList now has {len(self.raintips)} raintips")
			for raintip_listener in self.raintip_listeners:
				raintip_listener.raintipAdded(raintip)
			self.added_signal.emit()

	def removeRaintip(self, raintip: Raintip):
		for raintip_listener in self.raintip_listeners:
			raintip_listener.raintipRemoved(raintip)
		del self.raintips[raintip.getID()]

	def updateRaintip(self, raintip):
		for raintip_listener in self.raintip_listeners:
			raintip_listener.raintipUpdated(raintip)
		self.update_signal.emit()

	def getRaintipByID(self, id):
		if id in self.raintips.keys():
			return self.raintips[id]
		return None

	# listener infrastructure

	def registerRaintipListener(self, raintip_listener):
		self.raintip_listeners.append(raintip_listener)

	def unregisterRaintipListener(self, raintip_listener):
		self.raintip_listeners.remove(raintip_listener)


class RaintipListener():
	def rainttipAdded(self, rainttip):
		raise Exception(f"raintipAdded() not implemented in class {type(self)}")

	def raintipRemoved(self, raintip):
		raise Exception(f"raintipRemoved() not implemented in class {type(self)}")

	def raintipUpdated(self, raintip):
		raise Exception(f"raintipUpdated() not implemented in class {type(self)}")


##############################################################################################################################################
#                                                                                                                                            #
#    88888888ba             88                    88             88          88                   88                                         #
#    88      "8b            ""              ,d    ""             88          ""             ,d    88   ,d                                    #
#    88      ,8P                            88                   88                         88    88   88                                    #
#    88aaaaaa8P' ,adPPYYba, 88 8b,dPPYba, MM88MMM 88 8b,dPPYba,  88          88 ,adPPYba, MM88MMM 88 MM88MMM ,adPPYba, 88,dPYba,,adPYba,     #
#    88""""88'   ""     `Y8 88 88P'   `"8a  88    88 88P'    "8a 88          88 I8[    ""   88    88   88   a8P_____88 88P'   "88"    "8a    #
#    88    `8b   ,adPPPPP88 88 88       88  88    88 88       d8 88          88  `"Y8ba,    88    88   88   8PP""""""" 88      88      88    #
#    88     `8b  88,    ,88 88 88       88  88,   88 88b,   ,a8" 88          88 aa    ]8I   88,   88   88,  "8b,   ,aa 88      88      88    #
#    88      `8b `"8bbdP"Y8 88 88       88  "Y888 88 88`YbbdP"'  88888888888 88 `"YbbdP"'   "Y888 88   "Y888 `"Ybbd8"' 88      88      88    #
#                                                    88                                                                                      #
#                                                    88                                                                                      #
##############################################################################################################################################

class RaintipListItem(QTreeWidgetItem, PrintError):

	def __init__(self, o):
		if isinstance(o, list):
			QTreeWidgetItem.__init__(self, o)
		elif isinstance(o, Raintip):
			self.raintip = o
			self.raintip.raintiplist_item = self
			self.__init__(self.getDataArray(self.raintip))
		else:
			QTreeWidgetItem.__init__(self)
		self.refreshData()

	def getDataArray(self, raintip):
		return [
			raintip.getID(),
			raintip.comment.author.name,
			str(raintip.comment.score)
		]

	def refreshData(self):
		#self.print_error("refreshData() called from", threading.current_thread())
		data = self.getDataArray(self.raintip)
		for idx, value in enumerate(data, start=0):
			self.setData(idx, Qt.DisplayRole, value)
			# color = Qt.black
			# if self.tip.isFinished():
			# 	color = Qt.gray
			# 	if self.tip.acceptance_status == 'claimed': color = QColor(120, 180, 120)
			# 	if self.tip.acceptance_status == 'returned': color = QColor(180, 120, 120)
			# self.setForeground(idx, color)			
		QApplication.processEvents() # keep gui alive

##########################################################################################################################################################################
#                                                                                                                                                                        #
#    88888888ba             88                    88             88          88                 I8,        8        ,8I 88          88                                   #
#    88      "8b            ""              ,d    ""             88          ""             ,d  `8b       d8b       d8' ""          88                          ,d       #
#    88      ,8P                            88                   88                         88   "8,     ,8"8,     ,8"              88                          88       #
#    88aaaaaa8P' ,adPPYYba, 88 8b,dPPYba, MM88MMM 88 8b,dPPYba,  88          88 ,adPPYba, MM88MMM Y8     8P Y8     8P   88  ,adPPYb,88  ,adPPYb,d8  ,adPPYba, MM88MMM    #
#    88""""88'   ""     `Y8 88 88P'   `"8a  88    88 88P'    "8a 88          88 I8[    ""   88    `8b   d8' `8b   d8'   88 a8"    `Y88 a8"    `Y88 a8P_____88   88       #
#    88    `8b   ,adPPPPP88 88 88       88  88    88 88       d8 88          88  `"Y8ba,    88     `8a a8'   `8a a8'    88 8b       88 8b       88 8PP"""""""   88       #
#    88     `8b  88,    ,88 88 88       88  88,   88 88b,   ,a8" 88          88 aa    ]8I   88,     `8a8'     `8a8'     88 "8a,   ,d88 "8a,   ,d88 "8b,   ,aa   88,      #
#    88      `8b `"8bbdP"Y8 88 88       88  "Y888 88 88`YbbdP"'  88888888888 88 `"YbbdP"'   "Y888    `8'       `8'      88  `"8bbdP"Y8  `"YbbdP"Y8  `"Ybbd8"'   "Y888    #
#                                                    88                                                                                 aa,    ,88                       #
#                                                    88                                                                                  "Y8bbdP"                        #
##########################################################################################################################################################################

class RaintipListWidget(PrintError, MyTreeWidget, RaintipListener):

	default_sort = MyTreeWidget.SortSpec(1, Qt.AscendingOrder)

	def get_headers(self):
		headers = [
			_('ID'), 
			_('Author'),
			_('Upvotes')
		]
		
		return headers

	def __init__(self, wallet_ui, window: ElectrumWindow, raintip_list: RaintipList, reddit: Reddit):
		PrintError.__init__(self)
		# MyTreeWidget.__init__(self, window, self.create_menu, self.get_headers(), 10, [],  # headers, stretch_column, editable_columns
		# 	deferred_updates=True, save_sort_settings=True)
		MyTreeWidget.__init__(self, window, self.create_menu, self.get_headers(), 10, [],  # headers, stretch_column, editable_columns
			deferred_updates=True, save_sort_settings=True)
		self.wallet_ui = wallet_ui
		self.window = window
		self.reddit = reddit


		self.updated_raintips = []
		self.added_raintips = []

		self.setRaintiplist(raintip_list)

		if self.reddit == None:
			raise Exception("no reddit")

		self.print_error("RaintipListWidget.__init__()")
		self.setSelectionMode(QAbstractItemView.ExtendedSelection)
		self.setSortingEnabled(True)
		self.setIndentation(0)

	def __del__(self):
		if self.rainttiplist:
			# clean up signal connections
			self.tiplist.update_signal.disconnect(self.digestRaintipUpdates)
			self.tiplist.added_signal.disconnect(self.digestRaintipAdds)
			# deregister as tiplistener
			self.tiplist.unregisterRaintipListener(self)


	def setRaintiplist(self, raintip_list):
		if hasattr(self, "root_object") and self.raintiplist:
			self.tiplist.unregisterRaintipListener(self)

		#self.tips_by_address = dict()
		self.raintip_list = raintip_list

		# connect to tiplist added and update signals
		self.raintip_list.update_signal.connect(self.digestRaintipUpdates)
		self.raintip_list.added_signal.connect(self.digestRaintipAdds)

		# # register as TipListener
		# self.tiplist.registerTipListener(self)

	def create_menu(self, position):
		"""creates context-menu for single or multiply selected items"""

		col = self.currentColumn()
		column_title = self.headerItem().text(col)

		# create the context menu
		menu = QMenu()

	# TipListener implementation

	def raintipAdded(self, raintip):
		"""store added tip to local list for later digestion in gui thread"""
		self.added_raintips.append(raintip)
		self.print_error(f"{len(self.added_raintips)} added_raintips")

	def raintipUpdated(self, raintip):
		"""store updated tip to local list for later digestion in gui thread"""
		self.updated_raintips.append(raintip)

	def raintipRemoved(self, raintip):
		if hasattr(tip, 'raintiplist_item'):
			self.takeTopLevelItem(self.indexOfTopLevelItem(raintip.raintiplist_item))
			del raintip.raintiplist_item
		else:
			self.print_error("no raintiplist_item")

	def digestRaintipAdds(self):
		"""actually digest tip adds collected through raintipAdded() (runs in gui thread)"""
		added_raintips = self.added_raintips
		self.added_raintips = []

		if len(added_raintips) > 0: self.print_error(f"digesting {len(added_raintips)} raintip adds")

		for raintip in added_raintips:
			RaintipListItem(raintip) 

			self.addTopLevelItem(raintip.raintiplist_item)

	def digestRaintipUpdates(self):
		"""actually digest raintip updates collected through tipUpdated() (runs in gui thread)"""
		updated_raintips = self.updated_raintips
		self.updated_raintips = []

		if len(updated_raintips) > 0: self.print_error(f"digesting {len(updated_raintips)} raintip updates")

		for raintip in updated_raintips:
			if hasattr(raintip, 'raintiplist_item'):
				#self.print_error("digesting tip update for tip", tip)
				raintip.raintiplist_item.refreshData()
			else:
				self.updated_raintips.append(raintip)
				#self.print_error("trying to update tip without tiplistitem: ", tip, ", re-adding to updated_tips list")


	'''

	def calculateFiatAmount(self, tip):
		# calc tip.amount_fiat
		d_t = datetime.utcfromtimestamp(tip.chaintip_message_created_utc)
		fx_rate = self.window.fx.history_rate(d_t)

		tip.fiat_currency = self.window.fx.ccy
		if fx_rate and tip.amount_bch:
			try:
				tip.amount_fiat = fx_rate * tip.amount_bch
			except Exception as e:
				self.print_error("error with fx_rate", fx_rate, "tip amount", tip.amount_bch)
				traceback.print_exc(file=sys.stderr)
		else:
			tip.amount_fiat = None


	def do_export_history(self, filename):
		self.print_error(f"do_export_history({filename})")

		def csv_encode(s):
			if s is None or len(str(s)) == 0: return ""
			return '"' + str(s).replace('"', '\'') + '"'

		# prepare export_data list
		# export_data = [tip.to_dict() for tip in self.tiplist.tips.values()]
		export_data = []
		for tip in self.tiplist.tips.values():
			d = tip.to_dict()
			d = {**{
				"wallet": self.wallet.basename(),
				"payments": [{
					"txid": txid,
					"amount_bch": str(tip.payments_by_txhash[txid])
				} for txid in tip.payments_by_txhash.keys()]
			}, **d}
			export_data.append(d)

		# write json
		if filename.endswith(".json"):
			with open(filename, "w+", encoding='utf-8') as f:	
				f.write(json.dumps(export_data, indent=4))
			return True

		# write csv
		elif filename.endswith(".csv"):
			for d in export_data:
				self.print_error("dpam", d["payments"])
				d["payments"] = ",".join([p["txid"] for p in d["payments"]])
				self.print_error("d2", d)
			with open(filename, "w+", encoding='utf-8') as f:	
				f.write(",".join([csv_encode(d) for d in export_data[0].keys()]) + '\n')
				for data in export_data:
					f.write(",".join(csv_encode(d) for d in data.values()) + '\n')
			return True

		# extension detection fail
		self.print_error("failed to detect desired file format from extension. Aborting tip export.")
		return False

	def export_dialog(self, tips: list):
		d = WindowModalDialog(self.parent, _('Export {c} Tips').format(c=len(tips)))
		d.setMinimumSize(400, 200)
		vbox = QVBoxLayout(d)
		defaultname = os.path.expanduser(read_config(self.wallet, 'export_history_filename', f"~/ChainTipper tips - wallet {self.wallet.basename()}.csv"))
		select_msg = _('Select file to export your tips to')

		box, filename_e, csv_button = filename_field(self.config, defaultname, select_msg)

		vbox.addWidget(box)
		vbox.addStretch(1)
		hbox = Buttons(CancelButton(d), OkButton(d, _('Export')))
		vbox.addLayout(hbox)

		#run_hook('export_history_dialog', self, hbox)

		#self.update()
		res = d.exec_()
		d.setParent(None) # for python GC
		if not res:
			return
		filename = filename_e.text()
		write_config(self.wallet, 'export_history_filename', filename)
		if not filename:
			return
		success = False
		try:
			# minimum 10s time for calc. fees, etc
			success = self.do_export_history(filename)
		except Exception as reason:
			traceback.print_exc(file=sys.stderr)
			export_error_label = _("Error exporting tips")
			self.parent.show_critical(export_error_label + "\n" + str(reason), title=_("Unable to export tips"))
		else:
			if success:
				self.parent.show_message(_("{l} Tips successfully exported to {filename}").format(l=len(tips), filename=filename))
			else:
				self.parent.show_message(_("Exporting tips to {filename} failed. More detail might be seen in terminal output.").format(filename=filename))



	#

	'''


########################################################################################################################################################################################
#                                                                                                                                                                                      #
#    88888888ba             88                    88                                               88             88         88888888ba,   88            88                            #
#    88      "8b            ""              ,d    ""                                               88             ""   ,d    88      `"8b  ""            88                            #
#    88      ,8P                            88                                                     88                  88    88        `8b               88                            #
#    88aaaaaa8P' ,adPPYYba, 88 8b,dPPYba, MM88MMM 88 8b,dPPYba,  8b,dPPYba,   ,adPPYba, 8b,dPPYba, 88 8b,dPPYba,  88 MM88MMM 88         88 88 ,adPPYYba, 88  ,adPPYba,   ,adPPYb,d8    #
#    88""""88'   ""     `Y8 88 88P'   `"8a  88    88 88P'    "8a 88P'    "8a a8P_____88 88P'   "Y8 88 88P'   `"8a 88   88    88         88 88 ""     `Y8 88 a8"     "8a a8"    `Y88    #
#    88    `8b   ,adPPPPP88 88 88       88  88    88 88       d8 88       d8 8PP""""""" 88         88 88       88 88   88    88         8P 88 ,adPPPPP88 88 8b       d8 8b       88    #
#    88     `8b  88,    ,88 88 88       88  88,   88 88b,   ,a8" 88b,   ,a8" "8b,   ,aa 88         88 88       88 88   88,   88      .a8P  88 88,    ,88 88 "8a,   ,a8" "8a,   ,d88    #
#    88      `8b `"8bbdP"Y8 88 88       88  "Y888 88 88`YbbdP"'  88`YbbdP"'   `"Ybbd8"' 88         88 88       88 88   "Y888 88888888Y"'   88 `"8bbdP"Y8 88  `"YbbdP"'   `"YbbdP"Y8    #
#                                                    88          88                                                                                                      aa,    ,88    #
#                                                    88          88                                                                                                       "Y8bbdP"     #
########################################################################################################################################################################################

class RaintipperInitDialog(WindowModalDialog, PrintError, MessageBoxMixin):
	"""Dialog for initializing a RainTipper instance"""

	def redditObjectToString(self, o):
		s = None
		if type(o) == praw.models.Submission:
			s = f'Submission "{o.title}"'
		elif type(o) == praw.models.Comment:
			s = f'Comment "{o.body[:10]}"'
		elif type(o) == str:
			return o
		else:
			return f"Unknown type '{type(o)}', str(o): {str(o)}"

		return s + f" by {o.author}"

	def __init__(self, wallet_ui, parent):
		super().__init__(parent=parent, title=_("RainTipper Init Dialog"))
		self.setWindowIcon(icon_chaintip)
		self.wallet_ui = wallet_ui
		self.wallet = self.wallet_ui.wallet # TODO: remove and refactor to increase code clarity?

		# instantiate a Raintipper instance
		self.raintipper = Raintipper(self.wallet_ui)
		self.wallet_ui.reddit.addWorker(self.raintipper)

		# ensure only a single instance of this dialog to exist per wallet
		assert not hasattr(self.wallet, '_raintipper_init_dialog')
		main_window = self.wallet.weak_window()
		assert main_window
		self.wallet._raintipper_init_dialog = self

		# --- layout ---
		main_layout = QVBoxLayout(self)

		# header
		#main_layout.addWidget(QLabel(_('ChainTipper - settings for wallet "{wallet_name}"').format(wallet_name=self.wallet_ui.wallet_name)), 0, 0, Qt.AlignRight)

		# --- group for root object
		g_root_object = QGroupBox(_("Reddit Root Object"))
		grid = QGridLayout(g_root_object)
		main_layout.addWidget(g_root_object)

		# link or ID entry
		grid.addWidget(QLabel(_('Reddit URL to Submission or Comment')), 0, 1, Qt.AlignRight)
		self.root_object = QLineEdit()
		self.root_object.setText("https://www.reddit.com/r/chaintipper/comments/t3ahbo/raintipper_test/")
		def on_root_object_entered(): # used lambda for cleaner code
			self.raintipper.locateRootObject(self.root_object.text())
			self.root_object_found_label.setText(_("<looking up reddit object>"))
		self.root_object.editingFinished.connect(on_root_object_entered)
		grid.addWidget(self.root_object, 0, 2)

		# display found object
		grid.addWidget(QLabel(_('Found Reddit Object')), 1, 1, Qt.AlignRight)
		self.root_object_found_label = QLabel(_('<not found>'))
		grid.addWidget(self.root_object_found_label, 1, 2, Qt.AlignLeft)
		def on_root_object_located(o):
			self.print_error("on_root_object_located: ", o)
			self.root_object_found_label.setText(self.redditObjectToString(o))
			self.gobut.setEnabled(True)
		self.raintipper.root_object_located.connect(on_root_object_located)


		# close button
		cbut = CancelButton(self)
		cbut.setDefault(False)
		cbut.setAutoDefault(False)
		self.gobut = OkButton(self)
		self.gobut.setDefault(False)
		self.gobut.setAutoDefault(False)
		self.gobut.setDisabled(True)
		def on_go():
			self.raintipper.createTab() # create tab
			self.raintipper.show_tab()
		self.gobut.clicked.connect(on_go)
		main_layout.addLayout(Buttons(cbut, self.gobut))

	'''
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

	'''

	def closeEvent(self, event):
		super().closeEvent(event)
		self.wallet_ui.reddit.removeWorker(self.raintipper)
		#commit_config(self.wallet)
		if event.isAccepted():
			self.setParent(None)
			del self.wallet._raintipper_init_dialog

	def showEvent(self, event):
		super().showEvent(event)
