# -*- coding: utf-8 -*-

"""
Sci-API Unofficial API
[Search|Download] research papers from [scholar.google.com|sci-hub].

@author zaytoun (original), updated 2026
"""

import re
import argparse
import hashlib
import logging
import os
import time

import requests
import urllib3
from bs4 import BeautifulSoup
from retrying import retry

# log config
logging.basicConfig()
logger = logging.getLogger('Sci-Hub')
logger.setLevel(logging.DEBUG)

urllib3.disable_warnings()

# constants
SCHOLARS_BASE_URL = 'https://scholar.google.com/scholar'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                  'AppleWebKit/537.36 (KHTML, like Gecko) '
                  'Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
}

# Known working Sci-Hub mirrors (updated Feb 2026)
# Checked in order. Mirrors using sci.bban.top CDN listed first (direct
# embed/iframe links to PDFs). sci-hub.ru is the "real" Sci-Hub with
# self-hosted /storage/ paths and <object> tags.
SCIHUB_MIRRORS = [
    'https://sci-hub.vg',    # iframe, sci.bban.top CDN
    'https://sci-hub.al',    # embed, sci.bban.top CDN
    'https://sci-hub.mk',    # embed, sci.bban.top CDN
    'https://sci-hub.ru',    # object tag, self-hosted /storage/
]

# Delay between consecutive downloads (seconds) to avoid CAPTCHA/rate-limiting
DOWNLOAD_DELAY = 3


class SciHub(object):
    """
    SciHub class can search for papers on Google Scholars
    and fetch/download papers from sci-hub mirrors.
    """

    def __init__(self, mirrors=None):
        self.sess = requests.Session()
        self.sess.headers = HEADERS
        # User-provided mirrors take priority, then fall back to built-in list
        self._mirrors = list(mirrors) if mirrors else list(SCIHUB_MIRRORS)
        self.available_base_url_list = list(self._mirrors)
        self.base_url = self.available_base_url_list[0] + '/'
        self._last_download_time = 0

    def set_proxy(self, proxy):
        """Set proxy for session."""
        if proxy:
            self.sess.proxies = {
                "http": proxy,
                "https": proxy,
            }

    def _reset_mirrors(self):
        """Reset the mirror list back to full. Called at the start of each download."""
        self.available_base_url_list = list(self._mirrors)
        self.base_url = self.available_base_url_list[0] + '/'

    def _change_base_url(self):
        if not self.available_base_url_list:
            raise Exception('Ran out of valid sci-hub urls')
        del self.available_base_url_list[0]
        if not self.available_base_url_list:
            raise Exception('Ran out of valid sci-hub urls')
        self.base_url = self.available_base_url_list[0] + '/'
        logger.info("Switching to %s", self.base_url)

    def _rate_limit(self):
        """Enforce delay between downloads to avoid CAPTCHA."""
        elapsed = time.time() - self._last_download_time
        if elapsed < DOWNLOAD_DELAY:
            time.sleep(DOWNLOAD_DELAY - elapsed)
        self._last_download_time = time.time()

    def search(self, query, limit=10, download=False):
        """
        Performs a query on scholar.google.com, and returns a dictionary
        of results in the form {'papers': [{'name': ..., 'url': ...,
        'authors': ..., 'pdf': ...}, ...]}.

        Google Scholar requires a session with cookies to avoid CAPTCHA.
        """
        start = 0
        results = {'papers': []}

        # Hit Scholar homepage first to establish cookies
        try:
            self.sess.get('https://scholar.google.com/', timeout=15)
            time.sleep(1)
        except requests.exceptions.RequestException:
            pass  # proceed anyway, might still work

        while True:
            try:
                res = self.sess.get(
                    SCHOLARS_BASE_URL,
                    params={'q': query, 'start': start, 'hl': 'en'},
                    timeout=15
                )
            except requests.exceptions.RequestException as e:
                results['err'] = 'Failed to complete search with query %s (connection error)' % query
                return results

            if res.status_code == 429:
                results['err'] = 'Failed to complete search with query %s (rate limited, try again later)' % query
                return results

            s = self._get_soup(res.content)

            # Check for CAPTCHA
            if 'CAPTCHA' in str(res.content) or 'unusual traffic' in res.text.lower():
                results['err'] = 'Failed to complete search with query %s (captcha)' % query
                return results

            # Find result containers. gs_r is the outer wrapper; gs_ri is the
            # actual result item inside. Filter out non-result gs_r divs
            # (e.g., the citation dialog) by requiring gs_ri inside.
            papers = s.find_all('div', class_='gs_r')

            if not papers:
                return results

            for paper in papers:
                gs_ri = paper.find('div', class_='gs_ri')
                if not gs_ri:
                    continue

                source = None
                name = None
                authors = None
                pdf_url = None

                # Title and URL
                h3 = gs_ri.find('h3', class_='gs_rt')
                if h3:
                    name = h3.text.strip()
                    a = h3.find('a')
                    if a:
                        source = a['href']
                    else:
                        continue
                else:
                    continue

                # Author/venue info
                gs_a = gs_ri.find('div', class_='gs_a')
                if gs_a:
                    authors = gs_a.text.strip()

                # Free PDF link (shown on the right side of results)
                gs_ggs = paper.find('div', class_='gs_ggs')
                if gs_ggs:
                    pdf_a = gs_ggs.find('a')
                    if pdf_a:
                        pdf_url = pdf_a['href']
                # Alternative PDF location
                if not pdf_url:
                    gs_or = paper.find('div', class_='gs_or_ggsm')
                    if gs_or:
                        pdf_a = gs_or.find('a')
                        if pdf_a:
                            pdf_url = pdf_a['href']

                entry = {
                    'name': name,
                    'url': source,
                }
                if authors:
                    entry['authors'] = authors
                if pdf_url:
                    entry['pdf'] = pdf_url

                results['papers'].append(entry)

                if len(results['papers']) >= limit:
                    return results

            start += 10

    @retry(wait_random_min=100, wait_random_max=1000, stop_max_attempt_number=10)
    def download(self, identifier, destination='', path=None):
        """
        Downloads a paper from sci-hub given an identifier (DOI, PMID, URL).
        Currently, this can potentially be blocked by a captcha if a certain
        limit has been reached.
        """
        self._rate_limit()
        # Reset mirror list so a previous paper's failures don't starve this one
        self._reset_mirrors()
        data = self.fetch(identifier)

        if data and 'err' not in data:
            if destination:
                os.makedirs(destination, exist_ok=True)
            self._save(data['pdf'],
                       os.path.join(destination, path if path else data['name']))

        return data

    def fetch(self, identifier):
        """
        Fetches the paper by first retrieving the direct link to the pdf.
        If the identifier is a DOI, PMID, or URL pay-wall, then use Sci-Hub
        to access and download paper. Otherwise, just download paper directly.
        """
        try:
            url = self._get_direct_url(identifier)
            if not url:
                self._change_base_url()
                raise Exception('Could not find PDF URL for identifier %s' % identifier)

            res = self.sess.get(url, verify=False, timeout=30)

            content_type = res.headers.get('Content-Type', '')
            if 'application/pdf' not in content_type:
                self._change_base_url()
                logger.info('Failed to fetch pdf with identifier %s '
                            '(resolved url %s) due to captcha' % (identifier, url))
                raise CaptchaNeedException('Failed to fetch pdf with identifier %s '
                                           '(resolved url %s) due to captcha' % (identifier, url))

            # Validate PDF magic bytes
            if not res.content[:5].startswith(b'%PDF-'):
                self._change_base_url()
                raise Exception('Response claimed to be PDF but content is invalid '
                                'for identifier %s (url %s)' % (identifier, url))

            return {
                'pdf': res.content,
                'url': url,
                'name': self._generate_name(res)
            }

        except requests.exceptions.ConnectionError:
            logger.info('Cannot access %s, changing url', self.base_url)
            self._change_base_url()
            # Raise so @retry actually retries instead of returning None
            raise

        except requests.exceptions.RequestException as e:
            logger.info('Failed to fetch pdf with identifier %s due to request exception: %s',
                        identifier, str(e))
            return {
                'err': 'Failed to fetch pdf with identifier %s due to request exception: %s'
                       % (identifier, str(e))
            }

    def _get_direct_url(self, identifier):
        """Finds the direct source url for a given identifier."""
        id_type = self._classify(identifier)
        return identifier if id_type == 'url-direct' \
            else self._search_direct_url(identifier)

    def _search_direct_url(self, identifier):
        """
        Sci-Hub embeds papers in an iframe, embed, or object tag.
        This function finds the actual source url to the PDF.
        """
        res = self.sess.get(self.base_url + identifier, verify=False, timeout=30)

        # Check if sci-hub returned the PDF directly (some mirrors do this)
        if 'application/pdf' in res.headers.get('Content-Type', ''):
            return res.url

        s = self._get_soup(res.content)

        # Try iframe (classic sci-hub, sci-hub.vg)
        iframe = s.find('iframe')
        if iframe and iframe.get('src'):
            return self._normalize_url(iframe['src'])

        # Try embed (sci-hub.al, sci-hub.mk)
        embed = s.find('embed', type='application/pdf')
        if embed and embed.get('src'):
            return self._normalize_url(embed['src'])
        # Fallback: any embed with src
        if not embed:
            embed = s.find('embed')
            if embed and embed.get('src'):
                return self._normalize_url(embed['src'])

        # Try object (sci-hub.ru uses <object data="...">)
        obj = s.find('object')
        if obj and obj.get('data'):
            data_url = obj['data']
            if '.pdf' in data_url or '/pdf/' in data_url or '/storage/' in data_url:
                return self._normalize_url(data_url)

        # Try finding a direct download button onclick
        for btn in s.find_all('button', onclick=True):
            onclick = btn['onclick']
            match = re.search(r"location\.href\s*=\s*['\"]([^'\"]+\.pdf[^'\"]*)", onclick)
            if match:
                return self._normalize_url(match.group(1).replace('\\/', '/'))

        # Try script tags for PDF URLs
        for script in s.find_all('script'):
            txt = script.string or ''
            urls = re.findall(r'(https?://[^\s"<>\']+\.pdf(?:[^\s"<>\']*)?)', txt)
            if urls:
                return urls[0]

        return None

    def _normalize_url(self, url):
        """Normalize a URL: handle protocol-relative and relative URLs."""
        url = url.strip()
        # Remove fragment like #view=FitH or #navpanes=0
        url = re.sub(r'#.*$', '', url)

        if url.startswith('//'):
            return 'https:' + url
        elif url.startswith('/'):
            # Relative URL — prepend base
            return self.base_url.rstrip('/') + url
        elif url.startswith('http'):
            return url
        else:
            return self.base_url.rstrip('/') + '/' + url

    def _classify(self, identifier):
        """
        Classify the type of identifier:
        url-direct - openly accessible paper
        url-non-direct - pay-walled paper
        pmid - PubMed ID
        doi - digital object identifier
        """
        if identifier.startswith('http') or identifier.startswith('https'):
            if identifier.endswith('pdf'):
                return 'url-direct'
            else:
                return 'url-non-direct'
        elif identifier.isdigit():
            return 'pmid'
        else:
            return 'doi'

    def _save(self, data, path):
        """Save a file given data and a path."""
        with open(path, 'wb') as f:
            f.write(data)

    def _get_soup(self, html):
        """Return html soup."""
        return BeautifulSoup(html, 'html.parser')

    def _generate_name(self, res):
        """
        Generate unique filename for paper. Uses md5 hash of content
        plus the last part of the URL for readability.
        """
        name = res.url.split('/')[-1]
        name = re.sub(r'#.*$', '', name)
        name = re.sub(r'\?.*$', '', name)
        if not name.endswith('.pdf'):
            name += '.pdf'
        pdf_hash = hashlib.md5(res.content).hexdigest()[:8]
        return '%s-%s' % (pdf_hash, name[-60:])


class CaptchaNeedException(Exception):
    pass


def main():
    parser = argparse.ArgumentParser(
        description='SciHub - To remove all barriers in the way of science.')
    parser.add_argument('-d', '--download', metavar='(DOI|PMID|URL)',
                        help='tries to find and download the paper', type=str)
    parser.add_argument('-f', '--file', metavar='path',
                        help='pass file with list of identifiers and download each', type=str)
    parser.add_argument('-s', '--search', metavar='query',
                        help='search Google Scholars', type=str)
    parser.add_argument('-sd', '--search_download', metavar='query',
                        help='search Google Scholars and download if possible', type=str)
    parser.add_argument('-l', '--limit', metavar='N',
                        help='the number of search results to limit to', default=10, type=int)
    parser.add_argument('-o', '--output', metavar='path',
                        help='directory to store papers', default='', type=str)
    parser.add_argument('-v', '--verbose',
                        help='increase output verbosity', action='store_true')
    parser.add_argument('-p', '--proxy',
                        help='via proxy format like socks5://user:pass@host:port',
                        action='store', type=str)
    parser.add_argument('-m', '--mirror', metavar='URL',
                        help='use specific sci-hub mirror URL(s), can be repeated '
                             '(e.g. -m https://sci-hub.ru -m https://sci-hub.vg)',
                        action='append', type=str)

    args = parser.parse_args()

    if not args.verbose:
        logger.setLevel(logging.INFO)

    # User-provided mirrors override built-in defaults
    sh = SciHub(mirrors=args.mirror)

    if args.proxy:
        sh.set_proxy(args.proxy)

    if args.download:
        result = sh.download(args.download, args.output)
        if not result or 'err' in result:
            logger.error('Failed: %s', result.get('err', 'Unknown error') if result else 'No result')
        else:
            logger.info('Downloaded: %s', result['name'])
    elif args.search:
        results = sh.search(args.search, args.limit)
        if 'err' in results:
            logger.error('%s', results['err'])
        else:
            logger.info('Found %d results for query "%s"', len(results['papers']), args.search)
            for i, paper in enumerate(results['papers'], 1):
                pdf_indicator = ' [PDF]' if 'pdf' in paper else ''
                print('%d. %s%s' % (i, paper['name'], pdf_indicator))
                print('   %s' % paper['url'])
                if 'authors' in paper:
                    print('   %s' % paper['authors'])
                print()
    elif args.search_download:
        results = sh.search(args.search_download, args.limit)
        if 'err' in results:
            logger.error('%s', results['err'])
        else:
            logger.info('Found %d results, downloading...', len(results['papers']))
            for i, paper in enumerate(results['papers'], 1):
                logger.info('[%d/%d] %s', i, len(results['papers']), paper['name'])
                result = sh.download(paper['url'], args.output)
                if not result or 'err' in result:
                    logger.error('  Failed: %s',
                                 result.get('err', 'Unknown error') if result else 'No result')
                else:
                    logger.info('  Saved: %s', result['name'])
    elif args.file:
        with open(args.file, 'r') as f:
            identifiers = [line.strip() for line in f if line.strip()]
            total = len(identifiers)
            for i, identifier in enumerate(identifiers, 1):
                logger.info('[%d/%d] Downloading: %s', i, total, identifier)
                result = sh.download(identifier, args.output)
                if not result or 'err' in result:
                    logger.error('  Failed: %s',
                                 result.get('err', 'Unknown error') if result else 'No result')
                else:
                    logger.info('  Saved: %s', result['name'])
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
