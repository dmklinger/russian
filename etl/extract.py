import bz2
import os
import requests
import json
from collections import defaultdict
from copy import deepcopy
from bs4 import BeautifulSoup, NavigableString
from pymorphy2.analyzer import MorphAnalyzer

from dictionary import Word, cyrillic

os.makedirs('data', exist_ok=True)

morph = MorphAnalyzer()
session = requests.session()

try:
	with open('data/wiktionary_raw_data.json', 'r', encoding='utf-8') as f:
		wiktionary_cache = json.loads(f.read())
except:  # does not exist yet
	wiktionary_cache = {}

def get_viewstate(bs=None):
	if bs is None:
		url = "https://lcorp.ulif.org.ua/dictua/dictua.aspx"
		req = session.get(url)
		data = req.text
		bs = BeautifulSoup(data, features='lxml')
	return (
		bs.find("input", {"id": "__VIEWSTATE"}).attrs['value'],
		bs.find("input", {"id": "__VIEWSTATEGENERATOR"}).attrs['value'],
		bs.find("input", {"id": "__EVENTVALIDATION"}).attrs['value'],
	)

vs, vsg, ev = get_viewstate()

try:
	with open('data/inflection_raw_data.json', 'r', encoding='utf-8') as f:
		inflection_cache = json.loads(f.read())
except:
	inflection_cache = {}


def get_ontolex(use_cache=True):
	if use_cache and os.path.exists('data/raw_dbnary_dump.ttl'):
		return
	print('downloading latest ontolex data from dbnary')
	with session.get('http://kaiko.getalp.org/static/ontolex/latest/en_dbnary_ontolex.ttl.bz2', stream=True) as f:
		data = bz2.BZ2File(f.raw).read()
	print('decompressing')
	with open('data/raw_dbnary_dump.ttl', 'wb+', encoding='utf-8') as f:
		f.write(data)
	print('decompressing finished')


def get_superlative_adjectives():
	# I don't know why these aren't considered lemmas
	def add_words(words, results):
		for word in results['query']['categorymembers']:
			title = word['title']
			if 'Category' not in title:
				words.append(title)

	words = []

	results = session.get('https://en.wiktionary.org/w/api.php?action=query&list=categorymembers&cmtitle=Category:Russian_superlative_adjectives&format=json&cmlimit=max').json()
	add_words(words, results)

	while 'continue' in results:
		cmcontinue = results['continue']
		results = session.get(f'https://en.wiktionary.org/w/api.php?action=query&list=categorymembers&cmtitle=Category:Russian_superlative_adjectives&format=json&cmlimit=max&cmcontinue={cmcontinue}').json()
		add_words(words, results)
	
	return words


def get_lemmas():
	def add_words(words, results):
		for word in results['query']['categorymembers']:
			title = word['title']
			if 'Category' not in title:
				words.append(title)

	words = []

	results = session.get('https://en.wiktionary.org/w/api.php?action=query&list=categorymembers&cmtitle=Category:Russian_lemmas&format=json&cmlimit=max').json()
	add_words(words, results)

	while 'continue' in results:
		cmcontinue = results['continue']
		results = session.get(f'https://en.wiktionary.org/w/api.php?action=query&list=categorymembers&cmtitle=Category:Russian_lemmas&format=json&cmlimit=max&cmcontinue={cmcontinue}').json()
		add_words(words, results)
	
	return words + get_superlative_adjectives()


def get_wiktionary_word(word, use_cache=True):
	if word in wiktionary_cache and use_cache:
		article = wiktionary_cache[word]
	else:
		article = session.get(
			f'https://en.wiktionary.org/w/api.php?action=parse&page={word}&prop=text&formatversion=2&format=json'
		).json()['parse']['text']
		wiktionary_cache[word] = article
	article = BeautifulSoup(article, 'lxml')

	def clean_tag(tag):
		res = ''
		for child in tag.contents:
			if isinstance(child, NavigableString):
				res += str(child)
			elif child.name in ('sup', 'sub'):
				res += str(child)
			elif child.name in ('ol', 'ul'):
				None  # in this house we say NO to recursion
			elif child.name in ('li'):
				res += clean_tag(child) + ','
			else:
				res += clean_tag(child)
		return res

	results = []

	word_name = article.find_all('strong', {'class': 'Cyrl headword'}, lang='ru')
	for word_pointer in word_name[::-1]:
		bad_stuff = word_pointer.find_all(class_='reference')
		for bs in bad_stuff:
			bs.decompose()
		accented_name = word_pointer.text.strip()  # name
		word_info = word_pointer.parent.find('span', {'class': 'gender'})
		if word_info is not None:
			word_info = word_info.text.strip()
		w = Word(accented_name)
		pos_pointer = word_pointer.find_previous(['h3', 'h4'])
		pos = pos_pointer.span.text.lower()
		def_pointer = word_pointer.find_next('ol')
		ds = def_pointer.find_all('li')
		bad_stuff = def_pointer.find_all('span', class_='HQToggle') \
			+ def_pointer.find_all('abbr') \
			+ def_pointer.find_all('ul') \
			+ def_pointer.find_all(lang='ru-Latn') \
			+ def_pointer.find_all(class_='mention-gloss-paren annotation-paren') \
			+ def_pointer.find_all(class_='mention-gloss-double-quote') \
			+ def_pointer.find_all(class_='nyms synonym') \
			+ def_pointer.find_all(class_='citation-whole') \
			+ def_pointer.find_all(class_='plainlinks')
		for bs in bad_stuff:
			bs.decompose()
		for d in ds:	
			glosses = [g.extract().text.strip() for g in d.find_all(class_='mention-gloss')]
			if d.dl:
				d.dl.decompose()
			d = clean_tag(d)
			d = ' '.join(d.split())
			d = d.replace(' ,', ',')
			d = d.replace(' .', '.')
			d = d.replace(' :', ':')
			d = d.replace(' :', ':')
			d = d.replace(',:', ':')
			d = d.rstrip(',.:').strip()
			if len(d) > 0:
				w.add_definition(pos, d, human_audited=True)
				w.add_info(Word.replace_pos(pos), word_info)
			if len(glosses) > 0:
				for g in glosses:
					w.add_definition(pos, g, human_audited=True)
					w.add_info(Word.replace_pos(pos), word_info)
		inflection_pointer = word_pointer.parent
		if pos != 'verb':
			inflection_pointer = inflection_pointer.find_next('span', text='Declension')
		else:
			inflection_pointer = inflection_pointer.find_next('span', text='Conjugation')
		table = None
		if inflection_pointer is not None:
			table = inflection_pointer.find_next('table', {'class': 'inflection-table'}) 
		if table is None and inflection_pointer is not None:
			table = inflection_pointer.find_next('table', {'class': 'inflection-table inflection inflection-ru inflection-verb'})
		if table and len(w.usages.keys()) > 0:
			if 'Pre-reform' not in str(table.parent):
				forms, form_type = parse_wiktionary_table(accented_name, table) 
				w.add_forms(Word.replace_pos(pos), forms, form_type)
				table.extract()
		results.append(w)
	return results


def parse_wiktionary_table(w, inflections):

	def parse_verb(items):
		forms = defaultdict(lambda: [])
		for span in items:
			tense, number, gender, person, participle = None, None, None, None, None
			tense_info = span['class'][3].replace('-form-of', '').split('|')
			for t in tense_info:
				if t in ('inf', 'pres', 'past', 'fut', 'imp'):
					tense = t
				if t in ('m', 'f', 'n'):
					gender = t
				if t in ('1', '2', '3'):
					person = t
				if t in ('s', 'p'):
					number = t
				if t in ('act', 'pass', 'adv') and participle is None:
					participle = {'act': 'act', 'pass': 'pas', 'adv': 'adv'}[t]
			if tense == 'inf':
				form = tense
			elif participle is not None:
				form = f"{tense} {participle} pp"
			elif tense in ('pres', 'fut', 'imp'):
				form = f'{tense} {person}{number}'
			elif tense == 'past':
				if number == 's':
					form = f'past {gender}s'
				else:
					form = 'past p'
			forms[form].append(span.text.strip())
		forms = dict(forms)
		has_present = False
		for f in forms:
			if 'pres' in f:
				has_present = True
		if has_present:
			for f in list(forms.keys()):
				if 'fut' in f:
					del forms[f]
		return forms

	def parse_noun(items):
		forms = defaultdict(lambda: [])
		for span in items:
			case_info = span['class'][3].replace('-form-of', '').split('|')
			if len(case_info) < 2:
				forms[f"{case_info[0]} n"].append(span.text.strip())
			else:
				forms[f"{case_info[0]} n{case_info[1]}"].append(span.text.strip())
		forms = dict(forms)
		return forms

	def parse_adj(items):
		forms = defaultdict(lambda: [])
		for span in items:
			case_info = span['class'][3].replace('-form-of', '').split('|')
			if case_info[0] in ('an', 'in'):
				case_info = case_info[1:]
			if case_info[1] == 'p':
				form = f"{case_info[0]} ap"
				forms[form].append(span.text.strip())
			elif case_info[1] == 'm//n':
				form = f"{case_info[0]} am"
				forms[form].append(span.text.strip())
				form = f"{case_info[0]} an"
				forms[form].append(span.text.strip())
			elif case_info[1] == 'm':
				form = f"{case_info[0]} am"
				forms[form].append(span.text.strip())
			elif case_info[1] == 'n':
				form = f"{case_info[0]} an"
				forms[form].append(span.text.strip())
			else:
				form = f"{case_info[0]} af"
				forms[form].append(span.text.strip())
		forms = dict(forms)
		return forms

	def parse_pronoun(word):
		nom = ['я', 'ты', 'он', 'оно́', 'она́', 'мы', 'вы', 'они́', '']
		gen = ['меня́', 'тебя́', 'его́, него́', 'его́, него́', 'её, неё', 'нас', 'вас', 'их, них', 'себя́']
		dat = ['мне', 'тебе́', 'ему́, нему́', 'ему́, нему́', 'ей, ней', 'нам', 'вам', 'им, ним', 'себе́']
		acc = ['мене́', 'тебе́', 'его́, него́', 'его́, него́', 'её, неё', 'нас', 'вас', 'их, них', 'себя́']
		ins = ['мной, мно́ю', 'тобо́й, тобо́ю', 'им, ним', 'им, ним', 'ей, ней', 'на́ми', 'ва́ми', 'и́ми, ни́ми', 'собо́й']
		pre = ['мне', 'тебе́', 'нём', 'нём', 'ней', 'нас', 'вас', 'них', 'себе́']
		index = {}
		for l in [nom, gen, dat, acc, ins, pre]:
			for i, e in enumerate(l):
				index[e.replace('́', '')] = i
		word = word.replace('́', '')
		if word not in index:
			return None
		forms = defaultdict(lambda: [])
		forms['nom n'] += nom[index[word]].split(', ')
		forms['gen n'] += gen[index[word]].split(', ')
		forms['dat n'] += dat[index[word]].split(', ')
		forms['acc n'] += acc[index[word]].split(', ')
		forms['ins n'] += ins[index[word]].split(', ')
		forms['pre n'] += pre[index[word]].split(', ')
		forms = dict(forms)
		return forms

	items = [span for span in inflections.find_all('span', {'class': 'form-of', 'lang': 'ru'})]
	cat = None
	
	for i in items:
		row = i['class'][3].replace('-form-of', '').split('|')
		if cat is None and row[0] == 'inf':
			cat = 'verb'
		elif cat is None and len(row) == 1 and row[0] == 'nom':
			cat = 'noun'
		elif cat is None and row[1] == 'm//n':
			cat = 'adj'
		elif cat is None and row[1] == 's':
			cat = 'noun'
	if len(items) == 0:  # maybe a pronoun:
		items = [span for span in inflections.find_all('span', {'class': 'Cyrl', 'lang': 'ru'})]
		if len(items) > 0:
			cat = 'pronoun'
	forms = None
	form_type = None
	if cat == 'verb':
		form_type = 'verb'
		forms = parse_verb(items)
	if cat == 'noun':
		form_type = 'noun'
		forms = parse_noun(items)
	if cat == 'adj':
		form_type = 'adj'
		forms = parse_adj(items)
	if cat == 'pronoun':
		form_type = 'noun'
		forms = parse_pronoun(w)

	return forms, form_type


def dump_wiktionary_cache():
	with open(f'data/wiktionary_raw_data.json', 'w+', encoding='utf-8') as f:
		f.write(json.dumps(wiktionary_cache, ensure_ascii=False))


def get_frequency_list():
	try:
		with open('data/frequencies.json', 'r', encoding='utf-8') as f:
			data = json.loads(f.read())
	except:  # does not exist yet	
		article = session.get(
			f'https://en.wiktionary.org/w/api.php?action=parse&page=Appendix:Frequency_dictionary_of_the_modern_Russian_language_(the_Russian_National_Corpus)&prop=text&formatversion=2&format=json'
		).json()['parse']['text']
		article = BeautifulSoup(article, 'lxml')

		parts_of_speech = {
			'(part)': 'particle',
			'(s)': 'noun',
			'(pr)': 'preposition',
			'(a)': 'adjective',
			'(adv)': 'adverb',
			'(conj)': 'conjugation',
			'(advpro)': 'adverb',
			'(intj)': 'interjection',
			'(anum)': 'adjective',
			'(apro)': 'pronoun',
			'(num)': 'numeral',
			'(v)': 'verb',
			'(spro)': 'pronoun'
		}

		data = defaultdict(lambda: {})
		for i, li in enumerate(article.find_all('li')):
			word = li.a.extract().text.strip()
			pos = parts_of_speech[li.text.strip()]
			data[word][pos] = i + 1
		with open(f'data/frequencies.json', 'w+', encoding='utf-8') as f:
			f.write(json.dumps(data, indent=2, ensure_ascii=False))
	return data