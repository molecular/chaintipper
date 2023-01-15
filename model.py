from electroncash.util import PrintError, print_error
from decimal import Decimal
import weakref
from PyQt5.QtCore import QObject, pyqtSignal

######################################################
#                                                    #
#    88        88                                    #
#    88        88                                    #
#    88        88                                    #
#    88        88 ,adPPYba,  ,adPPYba, 8b,dPPYba,    #
#    88        88 I8[    "" a8P_____88 88P'   "Y8    #
#    88        88  `"Y8ba,  8PP""""""" 88            #
#    Y8a.    .a8P aa    ]8I "8b,   ,aa 88            #
#     `"Y8888Y"'  `"YbbdP"'  `"Ybbd8"' 88            #
#                                                    #
#                                                    #
######################################################

class User(PrintError):

	def __init__(self, name):
		self.name = name
		self.messages_by_id = dict()
		self.user_listeners = []

	def getID(self):
		return self.name

	def digestMessage(self, message):
		self.print_error(f"adding message {message.id} to user {self.name}")
		if message.id not in self.messages_by_id:
			self.messages_by_id[message.id] = message
			self.updated()

	def getMessageCount(self):
		return len(self.messages_by_id)

	def getUnreadMessageCount(self):
		return len([m for m in self.messages_by_id.values() if m.new])

	def getLatestMessage(self):
		if len(self.messages_by_id) == 0: return None
		return sorted(self.messages_by_id.values(), key=lambda m: m.created_utc)[-1]

	def getLatestUnreadMessage(self):
		if self.getUnreadMessageCount == 0: return None
		return sorted([m for m in self.messages_by_id.values() if m.new], key=lambda m: m.created_utc)[-1]

	def updated(self):
		for user_listener in self.user_listeners:
			user_listener.userUpdated(self)

	def registerUserListener(self, user_listener):
		self.user_listeners.append(user_listener)

	def unregisterUserListener(self, user_listener):
		self.user_listeners.remove(user_listener)


class UserListener():

	def userUpdated(self, user):
		raise Exception(f"userUpdated() not implemented in class {type(self)}")


#######################################################################################
#                                                                                     #
#    88        88                                 88          88                      #
#    88        88                                 88          ""             ,d       #
#    88        88                                 88                         88       #
#    88        88 ,adPPYba,  ,adPPYba, 8b,dPPYba, 88          88 ,adPPYba, MM88MMM    #
#    88        88 I8[    "" a8P_____88 88P'   "Y8 88          88 I8[    ""   88       #
#    88        88  `"Y8ba,  8PP""""""" 88         88          88  `"Y8ba,    88       #
#    Y8a.    .a8P aa    ]8I "8b,   ,aa 88         88          88 aa    ]8I   88,      #
#     `"Y8888Y"'  `"YbbdP"'  `"Ybbd8"' 88         88888888888 88 `"YbbdP"'   "Y888    #
#                                                                                     #
#                                                                                     #
#######################################################################################

class UserList(PrintError, QObject):

	def __init__(self):
		super(UserList, self).__init__()
		self.users_by_name = dict()

	def getUser(self, name):
		if name not in self.users_by_name:
			self.addUser(User(name))
		return self.users_by_name[name]

	def debug_stats(self):
		return f"          Userlist: {len(self.users_by_name)} users"

	def addUser(self, user):
		if user.getID() in self.users_by_name:
			raise Exception("addUser(): duplicate user.getID()")
		self.users_by_name[user.getID()] = user

	def removeUser(self, user):
		del self.users_by_name[user.getID()]


#####################################
#                                   #
#    888888888888 88                #
#         88      ""                #
#         88                        #
#         88      88 8b,dPPYba,     #
#         88      88 88P'    "8a    #
#         88      88 88       d8    #
#         88      88 88b,   ,a8"    #
#         88      88 88`YbbdP"'     #
#                    88             #
#                    88             #
#####################################

class Tip(PrintError, UserListener):
	def __init__(self, tiplist):
		self.tiplist_weakref = weakref.ref(tiplist)

		self.platform = 'unknown'

		# defaults
		self.status = "init"
		self.tipping_comment_id = None
		self.username = None
		self.recipient_address = None
		self.tipping_comment_id = None
		self.direction = None
		self.amount_bch = ""
		self.amount_bch = ""
		self.tip_amount_text = None
		self.tip_quantity = None
		self.tip_unit = None
		self.tip_op_return = None
		self.payment_status = None

		self.payments_by_txhash = {}
		self.amount_received_bch = None

	def getID(self):
		raise Exception("getID() not implemented by subclass")

	def to_dict(self):
		raise Exception("to_dict() not implemented by subclass")

	def from_dict(self):
		raise Exception("from_dict() not implemented by subclass")

	def update(self):
		if self.tiplist_weakref():
			self.tiplist_weakref().updateTip(self)
		else:
			self.print_error("weakref to tiplist broken, can't update tip", self)

	def remove(self):
		if self.tiplist_weakref():
			self.tiplist_weakref().removeTip(self)
		else:
			self.print_error("weakref to tiplist broken, can't remove tip", self)

	def registerPayment(self, txhash: str, amount_bch: Decimal, source: str):
		#self.print_error(f"registerPayment({txhash}, {amount_bch})")
		if not txhash in self.payments_by_txhash.keys():
			self.payments_by_txhash[txhash] = amount_bch
			if not self.amount_received_bch or type(self.amount_received_bch) != Decimal:
				self.amount_received_bch = amount_bch
			else:
				self.amount_received_bch += amount_bch
			if len(self.payments_by_txhash) == 1:
				self.payment_status = "paid"
			else:
				self.payment_status = f'paid ({len(self.payments_by_txhash)} txs)'
			self.update()

	# UserListener

	def userUpdated(self, user):
		self.update()

######################################################################
#                                                                    #
#    888888888888 88             88          88                      #
#         88      ""             88          ""             ,d       #
#         88                     88                         88       #
#         88      88 8b,dPPYba,  88          88 ,adPPYba, MM88MMM    #
#         88      88 88P'    "8a 88          88 I8[    ""   88       #
#         88      88 88       d8 88          88  `"Y8ba,    88       #
#         88      88 88b,   ,a8" 88          88 aa    ]8I   88,      #
#         88      88 88`YbbdP"'  88888888888 88 `"YbbdP"'   "Y888    #
#                    88                                              #
#                    88                                              #
######################################################################

class TipList(PrintError, QObject):
	update_signal = pyqtSignal() # shouldn't these be instance variables?
	added_signal = pyqtSignal()

	def __init__(self):
		super(TipList, self).__init__()
		self.tip_listeners = []
		self.tips = {} # tip instances by id (uses getID())

	def debug_stats(self):
		return f"           Tiplist: {len(self.tips)} tips"

	def registerTipListener(self, tip_listener):
		self.tip_listeners.append(tip_listener)

	def unregisterTipListener(self, tip_listener):
		self.tip_listeners.remove(tip_listener)

	def addTip(self, tip):
		if tip.getID() in self.tips.keys():
			raise Exception("addTip(): duplicate tip.getID()")
		self.tips[tip.getID()] = tip
		for tip_listener in self.tip_listeners:
			tip_listener.tipAdded(tip)
		self.added_signal.emit()

	def removeTip(self, tip):
		del self.tips[tip.getID()]
		for tip_listener in self.tip_listeners:
			tip_listener.tipRemoved(tip)

	def updateTip(self, tip):
		for tip_listener in self.tip_listeners:
			tip_listener.tipUpdated(tip)
		self.update_signal.emit()

class TipListener():

	def tipAdded(self, tip):
		raise Exception(f"tipAdded() not implemented in class {type(self)}")

	def tipRemoved(self, tip):
		raise Exception(f"tipRemoved() not implemented in class {type(self)}")

	def tipUpdated(self, tip):
		raise Exception(f"tipUpdated() not implemented in class {type(self)}")


