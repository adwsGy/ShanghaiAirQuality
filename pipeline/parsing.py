"""Parsing of hourly PM2.5 CSV records from national archives."""
import csv
import math
from collections import Counter, defaultdict

def parse_number(text):
    text=text.strip()
    if text.lower() in ('','nan','na','null','none'):return None,'missing_value'
    try:v=float(text)
    except ValueError:return None,'non_numeric_value'
    if not math.isfinite(v):return None,'nonfinite_value'
    if v<0:return None,'negative_value'
    return v,'ok'

def collapse_hour(candidates):
    """Conservative quarantine of discordant duplicate hour observations."""
    first=candidates[0]
    if any(x!=first for x in candidates[1:]):return None,'conflicting_duplicate',len(candidates)-1
    return first[0],first[1],len(candidates)-1

def parse_day(raw_bytes,expected_date,objects):
    audit={'file_status':'ok','pm25_rows':0,'invalid_time_rows':0,'date_mismatch_rows':0,'malformed_rows':0,'hours_present':'','column_ids':''}
    issues=[];cells={o:defaultdict(list) for o in objects};present=set()
    if not raw_bytes or raw_bytes.lstrip().lower().startswith((b'<html',b'<!doctype')):
        audit['file_status']='invalid_html_or_empty';return cells,present,audit,issues
    try:lines=raw_bytes.decode('utf-8-sig').splitlines()
    except UnicodeDecodeError:
        audit['file_status']='invalid_encoding';return cells,present,audit,issues
    try:header=next(csv.reader([lines[0]]))
    except (IndexError,csv.Error):header=[]
    if header[:3]!=['date','hour','type']:
        audit['file_status']='invalid_header';return cells,present,audit,issues
    positions={o:header.index(o) for o in objects if header.count(o)==1}
    present=set(positions);audit['column_ids']=';'.join(sorted(present));hours=[]
    for line_no,line in enumerate(lines[1:],2):
        prefix=line.split(',',3)
        if len(prefix)<3 or prefix[2].strip()!='PM2.5':continue
        row=next(csv.reader([line]));audit['pm25_rows']+=1
        if len(row)!=len(header):
            audit['malformed_rows']+=1;issues.append({'line':line_no,'reason':'field_count_mismatch','station_id':'','hour':''});continue
        if row[0]!=expected_date.replace('-',''):
            audit['date_mismatch_rows']+=1;issues.append({'line':line_no,'reason':'date_mismatch','station_id':'','hour':row[1]});continue
        try:hour=int(row[1])
        except ValueError:hour=-1
        if hour not in range(24):
            audit['invalid_time_rows']+=1;issues.append({'line':line_no,'reason':'invalid_hour','station_id':'','hour':row[1]});continue
        hours.append(hour)
        for o,col in positions.items():cells[o][hour].append(parse_number(row[col]))
    audit['hours_present']=';'.join(map(str,sorted(set(hours))))
    audit['duplicate_hour_rows']=sum(n-1 for n in Counter(hours).values())
    return cells,present,audit,issues

