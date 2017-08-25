
from pymongo import MongoClient

from datetime import datetime

import csv
import os

from scrapex import common

class DB(object):
	"""Provides a scaleable storage for big scrapes."""
	def __init__(self, config):
		
		self.config = config

		if 'host' in config:
			self.client = MongoClient(config['host'], config['port'])
		else:
			self.client = MongoClient()

		#init the database	
		self._db = self.client[config['dbname']]


	def exists_search(self, _id):
		_item = self.get_search(_id)
		if _item:
			return True
		else:
			return False	

	def insert_search(self, _id_or_dict):
		if isinstance(_id_or_dict, dict):
			#search dict provided
			
			_id_or_dict.update({'created': datetime.now()})
			return self._db.searches.insert(_id_or_dict)
		else:	
			#just _id provided
			return self._db.searches.insert({'_id': _id_or_dict, 'created': datetime.now()})

	def get_search(self, _id):
		return self._db.searches.find_one({'_id': _id})


	def remove_search(self, _id):
		self._db.searches.delete_one({'_id': _id})

	def count_searches(self):
		return self._db.searches.count({})
	
	def insert_item(self, item):
		if '_id' in item:
			#check for existence first
			if self.exists_item(item['_id']):
				return False

		for k in item:
			v = item[k]
			if isinstance(v,unicode):

				item[k] = v.encode('utf8')

		self._db.items.insert(item)

		return True


	def insert_items(self, items):
		self._db.items.insert_many(items)

	def insertorupdate_item(self, item):
		self._db.items.update_one({'_id': item['_id']},{'$set': item}, upsert=True)
	
	def get_item(self, _id):
		return self._db.items.find_one({'_id': _id})
	
	def remove_item(self, _id):
		self._db.items.delete_one({'_id': _id})

	def remove_items(self, conditions = {}):
		self._db.items.delete_many(conditions)

	
	def update_item(self, item):

		self._db.items.update_one({'_id': item['_id']},{'$set': item}, upsert=False)


	def count_items(self):
		return self._db.items.count({})

	def exists_item(self, _id):
		_item = self.get_item(_id)
		if _item:
			return True
		else:
			return False	
	
	def _compile_all_fields(self,include_hidden_fields = False):
		fields = []
		for item in self._db.items.find():
			for field in item.keys():
				if field.startswith('_'):
					#hidden field
					if not include_hidden_fields:
						continue

				if field not in fields:
					fields.append(field)

		return sorted(fields)

	def export_items(self, dest_file, query = None, fields = None, include_hidden_fields = False, multicol_fields={}):

		""" 
		@query: None means all items
		
		@fields: None means all fields

		"""
		if os.path.exists(dest_file):
			os.remove(dest_file)

		if not fields:
			fields =self._compile_all_fields(include_hidden_fields)

		format = common.DataItem(dest_file).subreg('\.([a-z]{2,5})$--is').lower()

		rows = []

		for item in self._db.items.find():
			res = []

			for field in fields:
				value = item.get(field) or ''

				if field in multicol_fields:
					maxcol = multicol_fields[field]

					parts = []
					if value is None:
						value = []

					if isinstance(value, list):
						parts = value
					
					else:
						parts = value.split('|')

					if len(parts) < maxcol:
						#normalize
						for i in xrange(maxcol-len(parts)):
							parts.append('')


					for i in xrange(maxcol):
						res.append('{} {}'.format(field, i+1))
						res.append(parts[i])

				else:	
					res.append(field)
					res.append(value)

					
			if format == 'csv':		
				common.save_csv(dest_file, res)
			else:
				rows.append(res)	

		
		if format == 'xls':
			import excellib
			excellib.save_xls(dest_file, rows)
		elif format == 'xlsx':
			import excellib
			excellib.save_xlsx(dest_file, rows)	







			