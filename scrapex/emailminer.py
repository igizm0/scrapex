
import os
import re
import time
import random

from scrapex import common, Doc, Scraper

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

import logging

logger = logging.getLogger(__name__)
s = Scraper(use_cache=False, show_status_message = False)

brs = []	

def mine_emails(url, br=None, deep_level=1):
	"""
	deep_level = 1: scrape home page and contact page only

	"""
	

	if not url: return []
	if not common.subreg(url, '^(http)'):
		url = 'http://'+url
	if '@' in url:
		return common.get_emails(url)

	domain = common.get_domain(url).lower()

	history = {}

	def _load_page(page_url, current_level):
		"""
		Please make sure this _url is not loaded yet, to avoid loaded twice

		"""
		logger.debug('mine_emails page %s, level %s', page_url, current_level)
		html = ''
		if br:
			try:
				br.get(page_url)

				html = br.page_source

			except Exception as e:
				logger.warn('failed to _load_page: %s', page_url)
				# logger.exception(e)
				raise e #to trigger new br

		else:
			
			html = s.load_html(page_url)		

		
		doc = Doc(url=page_url, html=html)
		#update loaded links
		links = doc.q("//a")
		
		sub_urls = []

		for link in links:
			_url = link.href()

			if domain not in _url.lower():
				continue

			if _url in history:
				continue
			if _url not in sub_urls:	
				sub_urls.append(_url)	

		history[page_url] = (current_level+1, sub_urls)


		return doc		
				


	def _parse_emails(doc):
		emails = []
		#firstly try to get emails from the links only because it's more reliable
		link_texts = doc.q("//a").join(' | ')
		
		for email in common.get_emails(link_texts):
		
			if '@' in email and email not in emails:
				emails.append(email)

		if not emails:
			#try with text only, not links
			html = doc.remove("//script").html()
			for email in common.get_emails(html):
		
				if '@' in email and email not in emails:
					emails.append(email)	
		return emails			

	def _load_subpages(level):
		#firstly, compile all the urls of this level in the history
		urls = []
		for url in history:
			_level, suburls = history[url]
			if _level != level:
				continue

			for suburl in suburls:
				if suburl in history:
					continue

				if suburl not in urls:
					urls.append(suburl)	

		logger.debug('mine emails in level %s, with %s urls to process', level, len(urls))
		for suburl in urls:			
		
			doc = _load_page(suburl, level)
			emails = _parse_emails(doc)
			if emails:
				#found emails on this page, enough
				return emails

		#not found
		return []		

	
	doc = _load_page(url, current_level = 1)
	emails = _parse_emails(doc)
	
	if emails:
		return emails

	contact_url = doc.x("//a[contains(@href,'contact') or contains(@href,'Contact')]/@href")
	if contact_url:
		doc = _load_page(contact_url, current_level = 2)
		emails = _parse_emails(doc)
		
		#when a contact page found, no need to dig further even if no emails found

		return emails
		
	
	#try with level 2

	if deep_level >=2:
		emails = _load_subpages(level=2)
		if emails:
			return emails

	#try with level 3

	if deep_level >=3:
		emails = _load_subpages(level=3)
		if emails:
			return emails

	
	#not found
	return []		
				


def mine_batch(db, cc=3, headless = True, retries = 3, batchsize = 200, use_br=True):
	"""
	mine emails for a db, and update directly

	"""

	cnt_failed_to_quit_br = 0
	
	
	logger.info('items with websites: %s', db._db.sites.count({
		
		'$and': [
			{'website': {'$exists':True} },

			{'website': {'$ne':''} },

			{'website': {'$ne': None} },

			]

		}))

	
	logger.info('items minded successfully: %s', db._db.sites.count( 
		{'_mined_emails': True },

		))



	def _worker(items):
		br = _create_br() if use_br else None

		for item in items:
			try:
				website = item.get('website') or item.get('Website')
				item['email'] = mine_emails(website, br=br)
				item['_mined_emails'] = True
				item['_use_br'] = use_br
				logger.info('%s >> %s', item['domain'], item['email'])

				db._db.sites.update_one({'_id': item['_id']}, {'$set': item })
				
			except Exception as e:
				logger.warn('failed to mine_emails for %s with error: %s', item.get('website'), e.message)

				item['_mined_emails'] = u'failed: {}'.format(e.message)
				item['_use_br'] = use_br

				db._db.sites.update_one({'_id': item['_id']}, {'$set': item })
				
				logger.exception(e)

				#restart the br
				if use_br:
					_quit_br(br)
					br = _create_br()

		if use_br:			
			_quit_br(br)

				

	def _pending_items():
		"""
		get the pending items to mine emails for

		"""
		items = []
		for item in db._db.sites.find():
			if len(items) >= batchsize:
				break
			
			if not item.get('website'):
				continue

			if item.get('email'):
				#already done
				continue

			if item.get('_mined_emails'):
				#already done, including failed one
				continue
			if item.get('_is_bad_website'):
				continue

			website = item['website']

			if '_is_bad_website' not in item:
				#check the status of website
				__is_bad_website = _is_bad_website(website)
				
				logger.info('checking for bad website: %s ==> %s', website, __is_bad_website)


				db._db.sites.update_one({'_id': item['_id']}, {'$set': { '_is_bad_website': __is_bad_website} })

				if __is_bad_website:
					continue


				
			items.append(item)	

		return items	

	def _reset_failed_items():	
		
		filter_failed_items = {'_mined_emails': {'$regex': re.compile( '.*failed.*', re.I) }}

		db._db.sites.update_many(filter_failed_items, {'$set': {'_mined_emails': None}})

		logger.info('reset failed items')


	def _create_br():
		logger.info('_create_br...')
		time.sleep(random.randint(2,6))

		#create one br instance per thread
		global brs
		brs = []

		
		chrome_options = Options()
		if headless:
			chrome_options.add_argument("--headless")

		#todo: adding page load timeout to each br instance

		br = webdriver.Chrome(chrome_options=chrome_options)

		return br

	def _quit_br(br):

		if not br:
			return

		try:
			logger.info('to quit br...')
			br.quit()

			logger.info('br quitted')

		except Exception as e:
			cnt_failed_to_quit_br += 1
			logger.info('cnt_failed_to_quit_br: %s', cnt_failed_to_quit_br)
			logger.exception(e)

			if cnt_failed_to_quit_br > 20:
				
				cnt_failed_to_quit_br = 0

				os.system('pkill -f Google')
				os.system('pkill -f google')
				os.system('pkill -f chrom')

				
	num_of_rounds = 1 + retries
	logger.info('num_of_rounds: %s', num_of_rounds)

	for _round in range(1, num_of_rounds+1):	
		
		logger.info('mine_batch, round: %s', _round)

		
		try:
			
			#start mining
			
			pending_items = None

			batch_no = 0
			while True:

				batch_no += 1
				skip_failed_items = True 
				pending_items = _pending_items()
				if not pending_items:
					return #finish all

				logger.info('mine_batch, round: %s, batch#: %s | items: %s', _round, batch_no, len(pending_items))


				parts = [part for part in chunks(pending_items, cc)]
				
				if cc > 1:
					# parts = zip(parts, brs) # assign one br for each part
					common.start_threads(parts, _worker, cc=cc )
				else:
					for part in parts:
						try:
							_worker(part)

						except Exception as e:
							logger.exception(e)	

				
		except Exception as e:
			logger.exception(e)		
		
		if _round < num_of_rounds:
			#not last round, reset the failed items
			_reset_failed_items()



def chunks(_list, no_of_parts):
	""" 
	split a list into mulitple equal parts

	"""
	
	_fake_cnt = 0
	if (len(_list) % no_of_parts) > 0:
		_fake_cnt = no_of_parts - (len(_list) % no_of_parts)
	_fakes = []
	if _fake_cnt >0:

		_fakes = ['__fake__' for i in xrange(_fake_cnt)]

	
	_list += _fakes
	assert len(_list) % no_of_parts == 0
	partsize = len(_list) / no_of_parts

	parts = []
	for i in range(0, len(_list), partsize):
		part = _list[i:i + partsize]
		if part[-1] == '__fake__':
			part = part[0: part.index('__fake__')]
		
		yield part

def _is_bad_website(website):
	
	if 'facebook' in website.lower():
		return True
	if 'fb.com' in website.lower():
		return True
	
	if 'twitter' in website.lower():
		return True

	if 'linkedin' in website.lower():
		return True
	
	if 'youtube' in website.lower():
		return True
	
	if 'walmart' in website.lower():
		return True
	if 'stores.toysrus.com' in website.lower():
		return True
		
	if 'apple.com' in website.lower():
		return True	
	if 'homedepot.com' in website.lower():
		return True	
	
	if 'locations.michaels.com' in website.lower():
		return True	

	

	
		
		

	if not website.lower().startswith('http'):
		website = 'http://{}'.format(website)
	try:
		doc = s.load(website)
		if doc.response.code != 200:
			return True	
	except Exception as e:
		logger.exception(e)	
	
	return False	
		

if __name__ == '__main__':
	# for part in chunks([0,1,2,3,4,5,6,7], 3):
	# 	print part

	l1 = [1,2,3]
	l2 = ['a','b','c']
	print zip(l1,l2)