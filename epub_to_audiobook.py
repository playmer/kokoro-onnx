#!/usr/bin/env python3

#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.

# Author: Mariano Simone (http://marianosimone.com)
# Version: 1.0
# Name: epub-thumbnailer
# Description: An implementation of a cover thumbnailer for epub files
# Installation: see README

import os
import re
from io import BytesIO
import shutil
import sys
import traceback
from xml.dom import minidom

import ebooklib.ebooklib.epub
import src.kokoro_tts as tts

try:
    from urllib.request import urlopen
except ImportError:  # Python 2
    from urllib import urlopen

import zipfile

img_ext_regex = re.compile(r'^.*\.(jpg|jpeg|png)$', flags=re.IGNORECASE)
cover_regex = re.compile(r'.*cover.*\.(jpg|jpeg|png)', flags=re.IGNORECASE)

def _get_rootfile_root(epub):
    # open the main container
    container = epub.open("META-INF/container.xml")
    container_root = minidom.parseString(container.read())

    # locate the rootfile
    elem = container_root.getElementsByTagName("rootfile")[0]
    rootfile_path = elem.getAttribute("full-path")

    # open the rootfile
    rootfile = epub.open(rootfile_path)
    return rootfile_path, minidom.parseString(rootfile.read())

def get_cover_from_manifest(epub):
    rootfile_path, rootfile_root = _get_rootfile_root(epub)

    # find possible cover in meta
    cover_id = None
    for meta in rootfile_root.getElementsByTagName("meta"):
        if meta.getAttribute("name") == "cover":
            cover_id = meta.getAttribute("content")
            break

    # find the manifest element
    manifest = rootfile_root.getElementsByTagName("manifest")[0]
    for item in manifest.getElementsByTagName("item"):
        item_id = item.getAttribute("id")
        item_properties = item.getAttribute("properties")
        item_href = item.getAttribute("href")
        item_href_is_image = img_ext_regex.match(item_href.lower())
        item_id_might_be_cover = item_id == cover_id or ('cover' in item_id and item_href_is_image)
        item_properties_might_be_cover = item_properties == cover_id or ('cover' in item_properties and item_href_is_image)
        if item_id_might_be_cover or item_properties_might_be_cover:
            return os.path.join(os.path.dirname(rootfile_path), item_href)

    return None

def get_cover_by_guide(epub):
    rootfile_path, rootfile_root = _get_rootfile_root(epub)

    for ref in rootfile_root.getElementsByTagName("reference"):
        if ref.getAttribute("type") == "cover":
            cover_href = ref.getAttribute("href")
            cover_file_path = os.path.join(os.path.dirname(rootfile_path), cover_href)

            # is html
            cover_file = epub.open(cover_file_path)
            cover_dom = minidom.parseString(cover_file.read())
            imgs = cover_dom.getElementsByTagName("img")
            if imgs:
                img = imgs[0]
                img_path = img.getAttribute("src")
                return os.path.relpath(os.path.join(os.path.dirname(cover_file_path), img_path))
    return None

def get_cover_by_filename(epub):
    no_matching_images = []
    for fileinfo in epub.filelist:
        if cover_regex.match(fileinfo.filename):
            return fileinfo.filename
        if img_ext_regex.match(fileinfo.filename):
            no_matching_images.append(fileinfo)
    return _choose_best_image(no_matching_images)

def _choose_best_image(images):
    if images:
        return max(images, key=lambda f: f.file_size)
    return None

def extract_cover(epub, book_path, cover_path):
    if cover_path:
        cover = epub.open(cover_path)
        data = BytesIO(cover.read())
        filename, file_extension = os.path.splitext(os.path.basename(cover_path))
        cover_path = f'{book_path}/cover{file_extension}'

        with open(cover_path, "wb") as f:
            f.write(data.getbuffer())
        return cover_path
    return ''


def try_strategies(book_path, epub):
    extraction_strategies = [get_cover_from_manifest, get_cover_by_guide, get_cover_by_filename]

    for strategy in extraction_strategies:
        try:
            cover_path = strategy(epub)
            #print(f'We got the path? {cover_path}')
            return extract_cover(epub, book_path, cover_path.replace("\\", "/"))
        except Exception as ex:
            print("Error getting cover using %s: " % strategy.__name__, ex)
    
    return ''

import wave
import subprocess
from pathlib import Path
import ebooklib.ebooklib.epub as epub
import ebooklib.ebooklib
from bs4 import BeautifulSoup

#####################################################################################################
## Table of Contents
def process_toc(book):
    toc_items = []
    def gather_toc(items, depth=0):
        for item in items:
            indent = "  " * depth
            if isinstance(item, tuple):
                section_title, section_items = item
                print(f"{indent}• Section: {section_title}")
                gather_toc(section_items, depth + 1)
            elif isinstance(item, epub.Link):
                # Skip if title suggests it's front matter
                if (item.title.lower() in ['copy', 'copyright', 'title page', 'cover'] or
                    item.title.lower().startswith('by')):
                    continue
                
                toc_items.append((item.title, item.href))
                #print(f"{indent}• {item.title} -> {item.href}")
    gather_toc(book.toc)

    return toc_items


#####################################################################################################
## Chapters
def process_chapters(book):
    items_map = {}
    for value in book.items:
        if type(value) is epub.EpubHtml:
            items_map[value.id] = value.file_name

    spine = []
    for value in book.spine:
        if value[0] in items_map:
            spine.append((value[0], items_map[value[0]], value[1]))

    chapters = []
    order = 0
    for item in spine:
        file_name = item[1]
        # Find the document
        doc = next((doc for doc in book.get_items_of_type(ebooklib.ebooklib.ITEM_DOCUMENT) 
                    if doc.file_name.endswith(file_name)), None)
        
        if doc:
            content = doc.get_content().decode('utf-8')
            soup = BeautifulSoup(content, "html.parser")
            
            # Get whole document content
            text_content = soup.get_text().strip()

            chapter_name, file_extension = os.path.splitext(os.path.basename(file_name))
            
            
            if text_content:
                order += 1

                chapters.append({
                    'title': chapter_name,
                    'content': text_content,
                    'order': order
                })

    return chapters



#####################################################################################################
## Merged Chapters and Files
def get_merged_chapters(chapters, chapter_files, toc_items):
    associated_chapters_and_files = []
    
    for chapter in chapters:
        for chapter_file in chapter_files:
            chapter_file_base_name, file_extension = os.path.splitext(os.path.basename(chapter_file))
            chapter_file_order_and_name = chapter_file_base_name.split('-', 1)
            chapter_file_order = chapter_file_order_and_name[0].lstrip('0')
            chapter_file_name = chapter_file_order_and_name[1]

            if chapter_file_order == str(chapter['order']) and chapter_file_name == chapter['title']:
                associated_chapters_and_files.append({
                    'title': chapter['title'],
                    'content': chapter['content'],
                    'order': chapter['order'],
                    'wav_file': chapter_file
                })
                break

    # for chapter in associated_chapters_and_files:
    #     print(f'\t{chapter['order']}; {chapter['title']}; {chapter['wav_file']}')
    associated_chapters = []
    
    #print("toc")
    for chapter in associated_chapters_and_files:
        added = False

        for toc_item in toc_items:
            file_and_refs = toc_item[1].split('#', 1)
            filename, ext = os.path.splitext(os.path.basename(file_and_refs[0]))

            
            if filename == chapter['title']:
                associated_chapters.append({
                    'title': chapter['title'],
                    'content': chapter['content'],
                    'order': chapter['order'],
                    'wav_file': chapter['wav_file'],
                    'actual_title': toc_item[0]
                })
                added = True
                #print(f"merged: {filename} and {chapter['title']}")
                break

        if not added:
            associated_chapters.append({
                'title': chapter['title'],
                'content': chapter['content'],
                'order': chapter['order'],
                'wav_file': chapter['wav_file'],
                'actual_title': None
            })

    # print("Associated")
    # for chapter in associated_chapters:
    #     print(f'\t{chapter['order']}; {chapter['actual_title']}; {chapter['wav_file']}')

    merged_chapters = []
    order = 1
    merging = False
    for i in range(len(associated_chapters)):
        if merging and (associated_chapters[i]['actual_title'] is not None):
            merged_chapters.append({
                'order': str(order).zfill(3),
                'chapter_title': associated_chapters[i]['actual_title'],
                'subchapters': [associated_chapters[i]]
            })
            order += 1
        elif merging and (associated_chapters[i]['actual_title'] is None):
            merged_chapters[len(merged_chapters) - 1]['subchapters'].append(associated_chapters[i])
        elif (not merging) and (associated_chapters[i]['actual_title'] is not None):
            merged_chapters.append({
                'order': str(order).zfill(3),
                'chapter_title': associated_chapters[i]['actual_title'],
                'subchapters': [associated_chapters[i]]
            })
            order += 1
            merging = True
        elif (not merging) and (associated_chapters[i]['actual_title'] is None): # This should only happen if the first item isn't a toc entry, just give it a generic name
            merged_chapters.append({
                'order': str(order).zfill(3),
                'chapter_title': 'Book Start',
                'subchapters': [associated_chapters[i]]
            })
            order += 1
            merging = True
        else:
            print("missed a case")
            exit(1)

    return merged_chapters


#####################################################################################################
## Create m4b
def merge_chapters(merged_chapters, book_path, metadata):
    merged_chapters_path = os.path.join(book_path, 'merged_chapters')
    os.makedirs(merged_chapters_path, exist_ok=True)

    start_ms = 0
    end_ms = 0

    for chapter in merged_chapters:
        chapter_data = []

        for subchapter in chapter['subchapters']:
            chunk_data = wave.open(subchapter['wav_file'], 'rb')
            chapter_data.append([chunk_data.getparams(), chunk_data.readframes(chunk_data.getnframes())])
            chunk_data.close()

        merged_chapter_file = os.path.join(merged_chapters_path, f'chapter_{chapter['order']}.wav')
        output = wave.open(merged_chapter_file, 'wb')
        output.setparams(chapter_data[0][0])
        for i in range(len(chapter_data)):
            output.writeframes(chapter_data[i][1])
        output.close()

        ret = subprocess.run(['ffprobe.exe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', merged_chapter_file], capture_output=True)
        if ret.returncode != 0:
            print(f'ffmpeg got mad: \r\nStdout: {ret.stdout}\r\nStderr: {ret.stderr}')
            exit(0)

        length_ms = int(float(ret.stdout.strip()) * 1000)
        end_ms += length_ms
        
        metadata += f'\n'
        metadata += f'[CHAPTER]\n'
        metadata += f'TIMEBASE=1/1000\n'
        metadata += f'START={start_ms}\n'
        metadata += f'END={end_ms}\n'
        metadata += f'title={chapter['chapter_title']}\n'
        start_ms += length_ms

    return metadata


def make_m4b(file_name, merged_chapters, book_path, book_name, artist):
    metadata =  f';FFMETADATA1\n'
    metadata += f'title={book_name}\n'
    metadata += f'album={book_name}\n'
    metadata += f'artist={artist}\n'
    metadata += f'composer=Kokoro TTS Michael\n'

    metadata = merge_chapters(merged_chapters, book_path, metadata)

    # Create the metadata file
    metadata_file = os.path.join(book_path, 'metadata.meta')
    with open(metadata_file, 'w', encoding='utf8') as f:
        f.write(metadata)
        
    # Create the book wav
    chapter_data = []
    merged_chapters_path = os.path.join(book_path, 'merged_chapters')
    for chapter in os.listdir(merged_chapters_path):
        chunk_data = wave.open(os.path.join(merged_chapters_path, chapter), 'rb')
        chapter_data.append([chunk_data.getparams(), chunk_data.readframes(chunk_data.getnframes())])
        chunk_data.close()

    temp_book_file = os.path.join(book_path, f'temp_book.wav')
    output = wave.open(temp_book_file, 'wb')
    output.setparams(chapter_data[0][0])
    for i in range(len(chapter_data)):
        output.writeframes(chapter_data[i][1])
    output.close()

    # Merge the book and metadata
    merged_book_file = os.path.join(book_path, f'book.wav')
    ret = subprocess.run(['ffmpeg', '-y', '-i', temp_book_file, '-c', 'copy', merged_book_file])
    if ret.returncode != 0:
        print(f'ffmpeg got mad: \r\nStdout: {ret.stdout}\r\nStderr: {ret.stderr}')
        exit(0)

    # Convert to m4b
    temp_book_file = os.path.join(book_path, f'book.m4b')
    ret = subprocess.run(['ffmpeg', '-y', '-i', merged_book_file, '-c:a', 'aac', '-b:a', '24k', temp_book_file], capture_output=True)

    if ret.returncode != 0:
        print(f'ffmpeg got mad: \r\nStdout: {ret.stdout}\r\nStderr: {ret.stderr}')
        exit(0)

    # Convert to m4b
    final_book_file = os.path.join('books', f'{book_name}.m4b')

    #-i book.m4b -i metadata.meta -i .\cover.jpg -map 0:a -map_metadata 1 -map_chapters 1 -map 2:v -disposition:v:0 attached_pic -c copy test.m4b
    ret = subprocess.run(['ffmpeg', '-y', '-i', temp_book_file, '-i', metadata_file, '-i', find_cover(book_path), '-map', '0:a', '-map_metadata', '1', '-map_chapters', '1', '-map', '2:v', '-disposition:v:0', 'attached_pic', '-c', 'copy', final_book_file], capture_output=True)

    if ret.returncode != 0:
        print(f'ffmpeg got mad: \r\nStdout: {ret.stdout}\r\nStderr: {ret.stderr}')
        exit(0)

    print('')


def find_cover(book_path):
    for file in os.listdir(book_path):
        file_name, file_extension = os.path.splitext(os.path.basename(file))
        if file_name == 'cover':
            return os.path.join(book_path, file)
    
    return 'cover.jpg'

def chunks_to_segments(chunks_path, segments_path):
    for chapter in os.listdir(chunks_path):
        chapter_data = []
        chapter_title = chapter
        print(f'\tMerging {chapter}')
        for chunk in os.listdir(os.path.join(chunks_path, chapter)):
            if chunk == 'info.txt':
                with open(os.path.join(chunks_path, chapter, chunk), 'r', encoding='utf8') as file:
                    #chapter_title = unicodedata.normalize('NFKD', file.read().replace('Title: ', '').strip())
                    chapter_title = file.read().replace('Title: ', '').strip()
                print(f'\t\t{chapter_title}')
                continue
            
            chunk_data = wave.open(os.path.join(chunks_path, chapter, chunk), 'rb')
            chapter_data.append([chunk_data.getparams(), chunk_data.readframes(chunk_data.getnframes())])
            chunk_data.close()

            #print(f'\t{chunk}')

        chapter_num = chapter.replace('chapter_', '')
        full_chapter_name = f'{chapter_num}-{chapter_title}'
        print(f'\t{full_chapter_name}.wav')

        output = wave.open(f'{segments_path}/{full_chapter_name}.wav', 'wb')
        output.setparams(chapter_data[0][0])
        for i in range(len(chapter_data)):
            output.writeframes(chapter_data[i][1])
        output.close()


# The epub library isn't as robust as the above in finding the cover, need to look into that.
def get_cover_from_book(book):
    for value in book.items:
        if type(value) is epub.EpubCover:
            return value.file_name
    
    return ''


# Which file are we working with?
def process_epub(input_file):

    try:
        book_name, book_file_extension = os.path.splitext(os.path.basename(input_file))
        chunks_path = os.path.join('books', 'processing', book_name)
        segments_path = Path(f"books/{book_name}/segments")
        book_path = Path(f"books/{book_name}")
            
        print(input_file)

        # if len(chapter_files) == 0:
        #     print('\tNot done generating audio...')
        #     return

        # if (book_name == 'ReZERO -Starting Life in Another World- Ex v02 - The Love Song of the Sword Devil'):
        #     print('\tSomething funky happening here...')
        #     return
        
        if not os.path.isdir(chunks_path):
            os.makedirs(chunks_path, exist_ok=True)
            tts.kokoro_tts(input_file=input_file, output_file=None, debug=True, voice='am_michael', split_output=chunks_path)
            #subprocess.run(['python', 'kokoro-tts', input_file, '--debug', '--voice', 'am_michael', '--split-output', chunks_path])

        segments_path.mkdir(parents=True, exist_ok=True)
        chunks_to_segments(chunks_path, segments_path)

        base_segment_files = os.listdir(segments_path)
        segment_files = []
        for chapter_file in base_segment_files:
            segment_files.append(os.path.join(segments_path, chapter_file))

        with open(input_file, "rb") as file:
            epub_file = zipfile.ZipFile(BytesIO(file.read()), "r")
            cover_path = try_strategies(book_path, epub_file)

        book = epub.read_epub(input_file, options={ 'ignore_ncx': True })
        
        toc_items = process_toc(book)
        chapters = process_chapters(book)

        if len(chapters) != len(segment_files):
            print("This book doesn't have all the chapters turned to audio expected")
            return
        
        any_non_wav = False
        for chapter_file in segment_files:
            chapter_name, file_extension = os.path.splitext(os.path.basename(chapter_file))
            if (file_extension != '.wav'):
                print(f"\tNon wav chapter: {chapter_file}")

        if any_non_wav:
            print('Skipping book due to non-wav chapter')
            return
        
        merged_chapters = get_merged_chapters(chapters, segment_files, toc_items)
        make_m4b(book_name, merged_chapters, book_path, book_name, 'Tappei Nagatsuki')
        os.replace(input_file, f'finished_epubs/{book_name}{book_file_extension}')
    except Exception as e:
        print(f"\nError: \n{e}")
        traceback_str = ''.join(traceback.format_tb(e.__traceback__))
        print(f"\nError: Full stack trace message: \n{traceback_str}")

        shutil.rmtree(chunks_path, True)
        shutil.rmtree(book_path, True)

if __name__ == "__main__":
    #process_epub("epubs_to_process/ReZERO -Starting Life in Another World- Ex v01 - The Dream of the Lion King.epub")
    for ebook in os.listdir("epubs_to_process"):
        ebook_path = os.path.join("epubs_to_process", ebook)
        process_epub(ebook_path)

    #process_epub(os.path.join("epubs_to_process", 'ReZERO -Starting Life in Another World- v05.epub'))
    #subprocess.run(['m4b-util', 'bind', chapters_path, '-c', cover_path, '--use-filenames'])