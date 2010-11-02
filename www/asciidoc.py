#!/usr/bin/env python
'''
asciidoc -  converts an AsciiDoc text file to DocBook, HTML or LinuxDoc

SYNOPSIS
asciidoc -b backend [ -d doctype ] [ -g glossary-entry ]
         [ -e ] [-n] [ -s ] [ -f configfile ] [ -o outfile ]
         [ --help | -h ] [ --version ] [ -v ] [ -c ]
         infile

DESCRIPTION
    The asciidoc(1) command translates the AsciiDoc text file 'infile'
    to the 'backend' formatted file 'outfile'. If 'infile' is '-' then
    the standard input is used.

OPTIONS
    --help, -h
        Print this documentation.

    -b
        Backend output file format: 'docbook', 'linuxdoc', 'html',
        'css' or 'css-embedded'.
    
    -c Dump configuration to stdout.

    -d
        Document type: 'article', 'manpage' or 'book'. The 'book'
        document type is only supported by the 'docbook' backend and
        the 'manpage' document type is not supported by the 'linuxdoc'
        backend.

    -e
        Exclude implicitly loaded configuration files except for those
        named like the input file ('infile.conf' and
        'infile-backend.conf').

    -f
        Use configuration file 'configfile'.

    -g
        Define glossary entry where 'glossary-entry' is formatted like
        'name=value'.  Alternate acceptable forms are 'name' (the
        'value' defaults to an empty string) and '^name' (undefine the
        'name' glossary entry).  Use the '-g section-numbers'
        command-line option to auto-number HTML article section
        titles.

    -n  Synonym for '-g section-numbers'.

    -o
        Write output to file 'outfile'. Defaults to the base name of
        input file with 'backend' extension. If the input is stdin
        then the outfile defaults to stdout. If 'outfile' is '-' then
        the standard output is used.

    -s
        Suppress document header and footer output.

    -v
        Verbosely print processing information to stderr.

    --version
        Print program version number.

BUGS
    - Keyboard EOF (Ctrl+D) ignored when reading source from console.
    - Reported line numbers in diagnostic messages are sometimes
      wrong.
    - Diagnostic messages are often not that illuminating.
    - Block filters only work in a UNIX environment.
    - Embedding open brace characters { in argument values can cause
      incorrect argument substitution.
    - Section numbering is incorrect when outputting HTML against a book
      type document with level 0 sections titles. This is not a biggy
      since multi-part books are generally processed to DocBook.

AUTHOR
    Written by Stuart Rackham, <srackham@methods.co.nz>

RESOURCES
    SourceForge: http://sourceforge.net/projects/asciidoc/
    Main website: http://www.methods.co.nz/asciidoc/

COPYING
    Copyright (C) 2002,2004 Stuart Rackham. Free use of this software is
    granted under the terms of the GNU General Public License (GPL).
'''

from __future__ import nested_scopes    # Only required for Python 2.1.
import sys, os, re, string, time, traceback, tempfile, popen2
from types import *

VERSION = '5.0.8'       # See CHANGLOG file for version history.

#---------------------------------------------------------------------------
# Utility functions and classes.
#---------------------------------------------------------------------------
# Allowed substitution options for subs List options and presubs and postsubs
# Paragraph options.
SUBS_OPTIONS = ('specialcharacters','quotes','specialwords','replacements',
    'glossary','macros','none','default')
# Default value for unspecified subs and presubs configuration file entries.
SUBS_DEFAULT = ('specialcharacters','quotes','specialwords','replacements',
    'glossary','macros')

class EAsciiDoc(Exception):
    pass

class staticmethod:
    '''Python 2.1 and earlier does not have the builtin staticmethod()
    function.'''
    def __init__(self,anycallable):
        self.__call__ = anycallable

from UserDict import UserDict

class OrderedDict(UserDict):
    '''Python Cookbook: Ordered Dictionary, Submitter: David Benjamin'''
    def __init__(self, dict = None):
        self._keys = []
        UserDict.__init__(self, dict)
    def __delitem__(self, key):
        UserDict.__delitem__(self, key)
        self._keys.remove(key)
    def __setitem__(self, key, item):
        UserDict.__setitem__(self, key, item)
        if key not in self._keys: self._keys.append(key)
    def clear(self):
        UserDict.clear(self)
        self._keys = []
    def copy(self):
        dict = UserDict.copy(self)
        dict._keys = self._keys[:]
        return dict
    def items(self):
        # zip() not available in Python 1.5.2
        #return zip(self._keys, self.values())
        result = []
        for k in self._keys:
            result.append((k,UserDict.__getitem__(self,k)))
        return result
    def keys(self):
        return self._keys
    def popitem(self):
        try:
            key = self._keys[-1]
        except IndexError:
            raise KeyError('dictionary is empty')
        val = self[key]
        del self[key]
        return (key, val)
    def setdefault(self, key, failobj = None):
        UserDict.setdefault(self, key, failobj)
        if key not in self._keys: self._keys.append(key)
    def update(self, dict):
        UserDict.update(self, dict)
        for key in dict.keys():
            if key not in self._keys: self._keys.append(key)
    def values(self):
        return map(self.get, self._keys)

def print_stderr(line):
    sys.stderr.write(line+os.linesep)

def verbose(msg,linenos=1):
    '''-v option messages.'''
    if config.verbose:
        console(msg,linenos=linenos)
def warning(msg,linenos=1):
    console(msg,'WARNING: ',linenos)
def console(msg, prefix='',linenos=1):
    '''Print warning message to stdout. 'offset' is added to reported line
    number for warnings emitted when reading ahead.'''
    s = prefix
    if linenos and reader.cursor:
        s = s + "%s: line %d: " \
            % (os.path.basename(reader.cursor[0]),reader.cursor[1])
    s = s + msg
    print_stderr(s)

def realpath(fname):
    '''Return the absolute pathname of the file fname. Follow symbolic links.
    os.realpath() not available in Python prior to 2.2 and not portable.'''
    # Follow symlinks to the actual executable.
    wd = os.getcwd()
    try:
        while os.path.islink(fname):
            linkdir = os.path.dirname(fname)
            fname = os.readlink(fname)
            if linkdir: os.chdir(linkdir)   # Symlinks can be relative.
        fname = os.path.abspath(fname)
    finally:
        os.chdir(wd)
    return fname

def assign(dst,src):
    '''Assign all attributes from 'src' object to 'dst' object.'''
    for a,v in src.__dict__.items():
        setattr(dst,a,v)

def strip_quotes(s):
    '''Trim white space and, if necessary, quote characters from s.'''
    s = string.strip(s)
    # Strip quotation mark characters from quoted strings.
    if len(s) >= 3 and s[0] == '"' and s[-1] == '"':
        s = s[1:-1]
    return s

def is_regexp(s):
    '''Return 1 if s is a valid regular expression else return 0.'''
    try: re.compile(s)
    except: return 0
    else: return 1

def join_regexp(relist):
    '''Join list of regular expressions re1,re2,... to single regular
    expression (re1)|(re2)|...'''
    if len(relist) == 0:
        return ''
    result = []
    # Delete named groups to avoid ambiguity.
    for s in relist:
        result.append(re.sub(r'\?P<\S+?>','',s))
    result = string.join(result,')|(')
    result = '('+result+')'
    return result

def validate(value,rule,errmsg):
    '''Validate value against rule expression. Throw EAsciiDoc exception with
    errmsg if validation fails.'''
    try:
        if not eval(string.replace(rule,'$',str(value))):
            raise EAsciiDoc,errmsg
    except:
        raise EAsciiDoc,errmsg
    return value

def join_lines(lines):
    '''Return a list in which lines terminated with the backslash line
    continuation character are joined.'''
    result = []
    s = ''
    continuation = 0
    for line in lines:
        if line and line[-1] == '\\':
            s = s + line[:-1]
            continuation = 1
            continue
        if continuation:
            result.append(s+line)
            s = ''
            continuation = 0
        else:
            result.append(line)
    if continuation:
        result.append(s)
    return result

def parse_args(args,dict,default_arg=None):
    '''Update a dictionary with name/value arguments from the args string.  The
    args string is a comma separated list of values and keyword name=value
    pairs. Values must preceed keywords and are named '1','2'... The entire
    args list is named '0'. If keywords are specified string values must be
    quoted. Examples:

    args: ''
    dict: {}

    args: 'hello,world'
    dict: {'2': 'world', '0': 'hello,world', '1': 'hello'}

    args: 'hello,,world'
    default_arg: 'caption'
    dict: {'3': 'world', 'caption': 'hello', '0': 'hello,,world', '1': 'hello'}

    args: '"hello",planet="earth"'
    dict: {'planet': 'earth', '0': '"hello",planet="earth"', '1': 'hello'}
    '''
    def f(*args,**keywords):
        # Name and add aguments '1','2'... to keywords.
        for i in range(len(args)):
            if not keywords.has_key(str(i+1)):
                keywords[str(i+1)] = args[i]
        return keywords

    if not args: return
    dict['0'] = args
    s = args
    try:
        d = eval('f('+s+')')
        # Parse special 'options' argument.
        if d.has_key('options') and d['options']:
            for opt in re.split(r'\s*,\s*',d['options']):
                if not is_name(opt):
                    warning('illegal option name in "%s"' % (d['options'],))
                else:
                    d[opt] = '' # Create blank entry for each option.
        dict.update(d)
    except:
        # Try quoting the args.
        s = string.replace(s,'"',r'\"') # Escape double-quotes.
        s = string.split(s,',')
        s = map(lambda x: '"'+string.strip(x)+'"',s)
        s = string.join(s,',')
        try:
            d = eval('f('+s+')')
        except:
            return  # If there's a syntax error leave with {0}=args.
        for k in d.keys():  # Drop any arguments that were missing.
            if d[k] == '': del d[k]
        dict.update(d)
    assert len(d) > 0
    if default_arg is not None and not d.has_key(default_arg) \
            and d.has_key('1'):
        dict[default_arg] = dict['1']

def parse_list(s):
    '''Parse comma separated string of Python literals. Return a tuple of of
    parsed values.'''
    try:
        result = eval('tuple(['+s+'])')
    except:
        raise EAsciiDoc,'malformed list: '+s
    return result

def parse_options(options,allowed,errmsg):
    '''Parse comma separated string of unquoted option names and return as a
    tuple of valid options. 'allowed' is a list of allowed option values.
    'errmsg' isan error message prefix if an illegal option error is thrown.'''
    result = []
    if options:
        for s in re.split(r'\s*,\s*',options):
            if s not in allowed:
                raise EAsciiDoc,'%s "%s"' % (errmsg,s)
            result.append(s)
    return tuple(result)

def is_name(s):
    '''Return 1 if s is valid glossary, macro or tag name.'''
    mo = re.match(r'\w[-\w]*',s)
    if mo is not None and s[-1] != '-': return 1
    else: return 0

def subs_quotes(text):
    '''Quoted text is marked up and the resulting text is
    returned.'''
    quotes = config.quotes.keys()
    # The quotes are iterated in reverse sort order to avoid ambiguity,
    # for example, '' is processed before '.
    quotes.sort()
    quotes.reverse()
    for quote in quotes:
        i = string.find(quote,'|')
        if i != -1 and quote != '|' and quote != '||':
            lq = quote[:i]
            rq = quote[i+1:]
        else:
            lq = rq = quote
        reo = re.compile(r'(?m)(^|\W)(?:' + re.escape(lq) + r')' \
            + r'(([\S].*?[^\s\\])|([\S]))(?:'+re.escape(rq)+r')(?=\W|$)')
        pos = 0
        while 1:
            mo = reo.search(text,pos)
            if not mo: break
            if text[mo.start()] == '\\':
                pos = mo.end()
            else:
                stag,etag = config.tag(config.quotes[quote])
                if stag == etag == None:
                    s = ''
                else:
                    s = mo.group(1) + stag + mo.group(2) + etag
                text = text[:mo.start()] + s + text[mo.end():]
                pos = mo.start() + len(s)
        text = string.replace(text,'\\'+lq, lq) # Unescape escaped quotes.
    return text

def subs_tag(tag,dict={}):
    '''Perform glossary substitution and split tag string returning start, end
    tag tuple (c.f. Config.tag()).'''
    s = subs_glossary((tag,),dict)[0]
    result = string.split(s,'|')
    if len(result) == 1:
        return result+[None]
    elif len(result) == 2:
        return result
    else:
        raise EAsciiDoc,'malformed tag "%s"' % (tag,)

def parse_entry(entry,dict=None,unquote=0,unique_values=0):
    '''Parse name=value entry to dictionary 'dict'. Return tuple (name,value)
    or None if illegal entry. If value is omitted (name=) then it is set to ''.
    If only the name is present the value is set to None).
    Leading and trailing white space is striped from 'name' and 'value'.
    'name' can contain any printable characters. If 'name includes the equals
    '=' character it must be escaped with a backslash.
    If 'unquote' is True leading and trailing double-quotes are stripped from
    'name' and 'value'.
    If unique_values' is True then dictionary entries with the same value are
    removed before the parsed entry is added.'''
    mo=re.search(r'[^\\](=)',entry)
    if mo:  # name=value entry.
        name = entry[:mo.start(1)]
        value = entry[mo.end(1):]
    else:   # name entry.
        name = entry
        value = None
    if unquote:
        name = strip_quotes(name)
        if value is not None:
            value = strip_quotes(value)
    else:
        name = string.strip(name)
        if value is not None:
            value = string.strip(value)
    if not name:
        return None
    if dict is not None:
        if unique_values:
            for k,v in dict.items():
                if v == value: del dict[k]
        dict[name] = value
    return name,value

def parse_entries(entries,dict,unquote=0,unique_values=0):
    '''Parse name=value entries from  from lines of text in 'entries' into
    dictionary 'dict'. Blank lines are skipped.'''
    for entry in entries:
        if entry and not parse_entry(entry,dict,unquote,unique_values):
            raise EAsciiDoc,'malformed section entry "%s"' % (entry,)

def undefine_entries(entries):
    '''All dictionary entries with None values are deleted.'''
    for k,v in entries.items():
        if v is None:
            del entries[k]

def dump_section(name,dict,f=sys.stdout):
    '''Write parameters in 'dict' as in configuration file section format with
    section 'name'.'''
    f.write('[%s]%s' % (name,writer.newline))
    for k,v in dict.items():
        k = str(k)
        # Quote if necessary.
        if len(k) != len(string.strip(k)):
            k = '"'+k+'"'
        if v and len(v) != len(string.strip(v)):
            v = '"'+v+'"'
        if v is None:
            # Don't dump undefined entries.
            continue
        else:
            s = k+'='+v
        f.write('%s%s' % (s,writer.newline))
    f.write(writer.newline)

def update_glossary(glossary,dict):
    '''Update 'glossary' dictionary with entries from parsed glossary section
    dictionary 'dict'.'''
    for k,v in dict.items():
        if not is_name(k):
            raise EAsciiDoc,'illegal "%s" glossary entry name' % (k,)
        glossary[k] = v

def readlines(fname):
    '''Read lines from file named 'fname' and strip trailing white space.'''
    # Read include file.
    f = open(fname)
    try:
        lines = f.readlines()
    finally:
        f.close()
    # Strip newlines.
    for i in range(len(lines)):
        lines[i] = string.rstrip(lines[i])
    return lines

def filter_lines(filter,lines,dict={}):
    '''Run 'lines' through the 'filter' shell command and return the result. The
    'dict' dictionary contains additional filter glossary entry parameters.'''
    if not filter:
        return lines
    if os.name != 'posix':
        warning('filters do not work in a non-posix environment')
        return lines
    # Perform glossary substitution on the filter command.
    f = subs_glossary((filter,),dict)
    if not f:
        raise EAsciiDoc,'filter "%s" has undefined parameter' % (filter,)
    filter = f[0]
    # Check in the 'filters' directory in both the asciidoc user and application
    # directories for the filter command.
    cmd = string.split(filter)[0]
    found = 0
    if not os.path.dirname(cmd):
        if USER_DIR:
            cmd2 = os.path.join(USER_DIR,'filters',cmd)
            if os.path.isfile(cmd2):
                found = 1
        if not found:
            cmd2 = os.path.join(APP_DIR,'filters',cmd)
            if os.path.isfile(cmd2):
                found = 1
        if found:
            filter = string.split(filter)
            filter[0] = cmd2
            filter = string.join(filter)
    verbose('filtering: '+filter, linenos=0)
    try:
        import select
        result = []
        r,w = popen2.popen2(filter)
        # Polled I/O loop to alleviate full buffer deadlocks.
        i = 0
        while i < len(lines):
            line = lines[i]
            if select.select([],[w.fileno()],[],0)[1]:
                w.write(line+os.linesep)    # Use platform line terminator.
                i = i+1
            if select.select([r.fileno()],[],[],0)[0]:
                s = r.readline()
                if not s: break             # Exit if filter output closes.
                result.append(string.rstrip(s))
        w.close()
        for s in r.readlines():
            result.append(string.rstrip(s))
        r.close()
    except:
        raise EAsciiDoc,'filter "%s" error' % (filter,)
    # There's no easy way to guage whether popen2() found and executed the
    # filter, so guess that if it produced no output there is probably a
    # problem.
    if lines and not result:
        warning('no output from filter "%s"' % (filter,))
    return result

def glossary_action(action, expr):
    '''Return the result of a glossary {action:expr} reference.'''
    verbose('evaluating: '+expr)
    if action == 'eval':
        result = None
        try:
            result = eval(expr)
            if result is not None:
                result = str(result)
        except:
            warning('{%s} "%s" expression evaluation error' % (action,expr))
    elif action in ('sys','sys2'):
        result = ''
        tmp = tempfile.mktemp()
        try:
            cmd = expr
            cmd = cmd + (' > %s' % tmp)
            if action == 'sys2':
                cmd = cmd + ' 2>&1'
            if os.system(cmd):
                warning('{%s} "%s" command non-zero exit status'
                    % (action,expr))
            try:
                if os.path.isfile(tmp):
                    lines = readlines(tmp)
                else:
                    lines = []
            except:
                raise EAsciiDoc,'{%s} temp file read error' % (action,)
            result = string.join(lines, writer.newline)
        finally:
            if os.path.isfile(tmp):
                os.remove(tmp)
    else:
        warning('Illegal {%s:} glossary action' % (action,))
    return result

def subs_glossary(lines,dict={}):
    '''Substitute 'lines' of text with glossary entries from the global
    document.glossary dictionary and from the 'dict' dictionary ('dict' entries
    take precedence). Return a tuple of the substituted lines.  'lines'
    containing non-matching substitution parameters are deleted. None glossary
    values are not substituted but '' glossary values are.'''

    def end_brace(text,start):
        '''Return index following end brace that matches brace at start in
        text.'''
        assert text[start] == '{'
        n = 0
        result = start
        for c in text[start:]:
            # Skip braces that are followed by a backslash.
            if result == len(text)-1 or text[result+1] != '\\':
                if c == '{': n = n + 1
                elif c == '}': n = n - 1
            result = result + 1
            if n == 0: break
        return result

    lines = list(lines)
    # Merge glossary and macro arguments (macro args take precedence).
    gloss = document.glossary.copy()
    gloss.update(dict)
    # Substitute all occurences of all dictionary parameters in all lines.
    for i in range(len(lines)-1,-1,-1): # Reverse iterate lines.
        text = lines[i]
        # Make it easier for regular expressions.
        text = string.replace(text,'\\{','{\\')
        text = string.replace(text,'\\}','}\\')
        # Expand literal glossary references of form {name}.
        # Nested glossary entries not allowed.
        reo = re.compile(r'\{(?P<name>[^\\\W][-\w]*?)\}(?!\\)', re.DOTALL)
        pos = 0
        while 1:
            mo = reo.search(text,pos)
            if not mo: break
            s =  gloss.get(mo.group('name'))
            if s is None:
                pos = mo.end()
            else:
                s = str(s)
                text = text[:mo.start()] + s + text[mo.end():]
                pos = mo.start() + len(s)
        # Expand conditional glossary references of form {name=value},
        # {name?value}, {name!value} and {name#value}.
        reo = re.compile(r'\{(?P<name>[^\\\W][-\w]*?)(?P<op>\=|\?|!|#|%)' \
            r'(?P<value>.*?)\}(?!\\)',re.DOTALL)
        pos = 0
        while 1:
            mo = reo.search(text,pos)
            if not mo: break
            name =  mo.group('name')
            lval =  gloss.get(name)
            op = mo.group('op')
            # mo.end() is not good enough because '{x={y}}' matches '{x={y}'.
            end = end_brace(text,mo.start())
            rval = text[mo.start('value'):end-1]
            if lval is None:
                # name glossary entry is undefined.
                if op == '=': s = rval
                elif op == '?': s = ''
                elif op == '!': s = rval
                elif op == '#': s = '{'+name+'}'    # So the line is deleted.
                elif op == '%': s = rval
                else: assert 1,'illegal glossary operator'
            else:
                # name glossary entry is defined.
                if op == '=': s = lval
                elif op == '?': s = rval
                elif op == '!': s = ''
                elif op == '#': s = rval
                elif op == '%': s = '{zzzzz}'   # So the line is deleted.
                else: assert 1,'illegal glossary operator'
            s = str(s)
            text = text[:mo.start()] + s + text[end:]
            pos = mo.start() + len(s)
        # Drop line if it contains  unsubstituted {name} references. 
        skipped = re.search(r'\{[^\\\W][-\w]*?\}(?!\\)', text, re.DOTALL)
        if skipped:
            del lines[i]
            continue;
        # Expand calculated glossary references of form {name:expression}.
        reo = re.compile(r'\{(?P<action>[^\\\W][-\w]*?):(?P<expr>.*?)\}(?!\\)',
            re.DOTALL)
        skipped = 0
        pos = 0
        while 1:
            mo = reo.search(text,pos)
            if not mo: break
            expr = mo.group('expr')
            expr = string.replace(expr,'{\\','{')
            expr = string.replace(expr,'}\\','}')
            s = glossary_action(mo.group('action'),expr)
            if s is None:
                skipped = 1
                break
            text = text[:mo.start()] + s + text[mo.end():]
            pos = mo.start() + len(s)
        # Drop line if the action returns None.
        if skipped:
            del lines[i]
            continue;
        # Remove backslash from escaped entries.
        text = string.replace(text,'{\\','{')
        text = string.replace(text,'}\\','}')
        lines[i] = text
    return tuple(lines)

class Lex:
    '''Lexical analysis routines. Static methods and attributes only.'''
    prev_element = None
    prev_cursor = None
    def __init__(self):
        raise AssertionError,'no class instances allowed'
    def next():
        '''Returns class of next element on the input (None if EOF).  The
        reader is assumed to be at the first line following a previous element,
        end of file or line one.  Exits with the reader pointing to the first
        line of the next element or EOF (leading blank lines are skipped).'''
        reader.skip_blank_lines()
        if reader.eof(): return None
        # Optimization: If we've already checked for an element at this
        # position return the element.
        if Lex.prev_element and Lex.prev_cursor == reader.cursor:
            return Lex.prev_element
        result = None
        # Check for BlockTitle.
        if not result and BlockTitle.isnext():
            result = BlockTitle
        # Check for Title.
        if not result and Title.isnext():
            result = Title
        # Check for Block Macro.
        if not result and macros.isnext():
            result = macros.current
        # Check for List.
        if not result and lists.isnext():
            result = lists.current
        # Check for DelimitedBlock.
        if not result and blocks.isnext():
            # Skip comment blocks.
            if 'skip' in blocks.current.options:
                blocks.current.translate()
                return Lex.next()
            else:
                result = blocks.current
        # Check for Table.
        if not result and tables.isnext():
            result = tables.current
        # If it's none of the above then it must be an Paragraph.
        if not result:
            if not paragraphs.isnext():
                raise EAsciiDoc,'paragraph expected'
            result = paragraphs.current
        # Cache answer.
        Lex.prev_cursor = reader.cursor
        Lex.prev_element = result
        return result       
    next = staticmethod(next)

    def title_parse(lines):
        '''Check for valid title at start of tuple lines. Return (title,level)
        tuple or None if invalid title.'''
        if len(lines) < 2: return None
        title,ul = lines[:2]
        # Title can't be blank.
        if len(title) == 0: return None
        if len(ul) < 2: return None
        # Fast check.
        if ul[:2] not in Title.underlines: return None
        # Length of underline must be within +-3 of title.
        if not (len(ul)-3 < len(title) < len(ul)+3): return None
        # Underline must be have valid repetition of underline character pairs.
        s = ul[:2]*((len(ul)+1)/2)
        if ul != s[:len(ul)]: return None
        return title,list(Title.underlines).index(ul[:2])
    title_parse = staticmethod(title_parse)

    def subs_1(s,options):
        '''Perform substitution specified in 'options' (in 'options' order) on
        a single line 's' of text.  Returns the substituted string.'''
        if not s:
            return s
        result = s
        for o in options:
            if o == 'specialcharacters':
                result = config.subs_specialchars(result)
            # Quoted text.
            elif o == 'quotes':
                result = subs_quotes(result)
            # Special words.
            elif o == 'specialwords':
                result = config.subs_specialwords(result)
            # Replacements.
            elif o == 'replacements':
                result = config.subs_replacements(result)
            # Inline macros.
            elif o == 'macros':
                result = macros.subs(result)
            else:
                raise EAsciiDoc,'illegal "%s" substitution option' % (o,)
        return result
    subs_1 = staticmethod(subs_1)

    def subs(lines,options):
        '''Perform inline processing specified by 'options' (in 'options'
        order) on sequence of 'lines'.'''
        if len(options) == 1:
            if options[0] == 'none':
                options = ()
            elif options[0] == 'default':
                options = SUBS_DEFAULT
        if not lines or not options:
            return lines
        for o in options:
            if o == 'glossary':
                lines = subs_glossary(lines)
            else:
                tmp = []
                for s in lines:
                    s = Lex.subs_1(s,(o,))
                    tmp.append(s)
                lines = tmp
        return lines
    subs = staticmethod(subs)

    def set_margin(lines, margin=0):
        '''Utility routine that sets the left margin to 'margin' space in a
        block of non-blank lines.'''
        # Calculate width of block margin.
        lines = list(lines)
        width = len(lines[0])
        for s in lines:
            i = re.search(r'\S',s).start()
            if i < width: width = i
        # Strip margin width from all lines.
        for i in range(len(lines)):
            lines[i] = ' '*margin + lines[i][width:]
        return lines
    set_margin = staticmethod(set_margin)

#---------------------------------------------------------------------------
# Document element classes parse AsciiDoc reader input and write DocBook writer
# output.
#---------------------------------------------------------------------------
class Document:
    def __init__(self):
        self.doctype = None     # 'article','manpage' or 'book'.
        self.backend = None     # -b option argument.
        self.glossary = {}      # Combined glossary entries.
        self.level = 0          # 0 => front matter. 1,2,3 => sect1,2,3.
    def init_glossary(self):
        # Set derived glossary enties.
        d = time.localtime(time.time())
        self.glossary['localdate'] = time.strftime('%d-%b-%Y',d)
        s = time.strftime('%H:%M:%S',d)
        if time.daylight:
            self.glossary['localtime'] = s + ' ' + time.tzname[1]
        else:
            self.glossary['localtime'] = s + ' ' + time.tzname[0]
        self.glossary['asciidoc-version'] = VERSION
        self.glossary['backend'] = document.backend
        self.glossary['doctype'] = document.doctype
        self.glossary['backend-'+document.backend] = ''
        self.glossary['doctype-'+document.doctype] = ''
        self.glossary[document.backend+'-'+document.doctype] = ''
        self.glossary['asciidoc-dir'] = APP_DIR
        self.glossary['user-dir'] = USER_DIR
        if reader.fname:
            self.glossary['infile'] = reader.fname
        if writer.fname:
            self.glossary['outfile'] = writer.fname
            s = os.path.splitext(writer.fname)[1][1:]   # Output file extension.
            self.glossary['filetype'] = s
            self.glossary['filetype-'+s] = ''
        # Update with conf file entries.
        self.glossary.update(config.conf_gloss)
        # Update with command-line entries.
        self.glossary.update(config.cmd_gloss)
        # Set configuration glossary entries.
        config.load_miscellaneous(config.conf_gloss)
        config.load_miscellaneous(config.cmd_gloss)
        self.glossary['newline'] = config.newline   # Use raw (unescaped) value.
    def translate(self):
        assert self.doctype in ('article','manpage','book'), \
            'illegal document type'
        assert self.level == 0
        # Process document header.
        has_header =  Lex.next() is Title and Title.level == 0
        if self.doctype == 'manpage' and not has_header:
            raise EAsciiDoc,'manpage document title is mandatory'
        if has_header:
            Header.parse()
            # Command-line entries override header derived entries.
            self.glossary.update(config.cmd_gloss)
            if not config.suppress_headers:
                hdr = config.subs_section('header',{})
                writer.write(hdr)
            if self.doctype in ('article','book'):
                # Translate 'preamble' (untitled elements between header
                # and first section title).
                if Lex.next() is not Title:
                    stag,etag = config.section2tags('preamble')
                    writer.write(stag)
                    Section.translate_body()
                    writer.write(etag)
            else:
                # Translate manpage SYNOPSIS.
                if Lex.next() is not Title:
                    raise EAsciiDoc,'second section must be SYNOPSIS'
                Title.parse()
                if string.upper(Title.dict['title']) <> 'SYNOPSIS':
                    raise EAsciiDoc,'second section must be SYNOPSIS'
                if Title.level != 1:
                    raise EAsciiDoc,'SYNOPSIS section title must be level 1'
                stag,etag = config.section2tags('sect-synopsis')
                writer.write(stag)
                Section.translate_body()
                writer.write(etag)
        else:
            if not config.suppress_headers:
                hdr = config.subs_section('header',{})
                writer.write(hdr)
            if Lex.next() is not Title:
                Section.translate_body()
        # Process remaining sections.
        while not reader.eof():
            if Lex.next() is not Title:
                raise EAsciiDoc,'section title expected'
            Section.translate()
        Section.setlevel(0) # Write remaining unwritten section close tags.
        # Substitute document parameters and write document footer.
        if not config.suppress_headers:
            ftr = config.subs_section('footer',{})
            writer.write(ftr)

class Header:
    '''Static methods and attributes only.'''
    def __init__(self):
        raise AssertionError,'no class instances allowed'
    def parse():
        assert Lex.next() is Title and Title.level == 0
        Title.parse()
        gloss = document.glossary   # Alias for readability.
        gloss['doctitle'] = Title.dict['title']
        if document.doctype == 'manpage':
            # manpage title formatted like mantitle(manvolnum).
            mo = re.match(r'^(?P<mantitle>.*)\((?P<manvolnum>.*)\)$',
                Title.dict['title'])
            if not mo: raise EAsciiDoc,'malformed manpage title'
            gloss['mantitle'] = string.strip(string.lower(mo.group('mantitle')))
            gloss['manvolnum'] = string.strip(mo.group('manvolnum'))
        s = reader.read_next()
        if s:
            # Parse author line.
            s = reader.read()
            s = subs_glossary([s])[0]
            s = string.strip(s)
            mo = re.match(r'^(?P<name1>[^<>\s]+)'
                    '(\s+(?P<name2>[^<>\s]+))?'
                    '(\s+(?P<name3>[^<>\s]+))?'
                    '(\s+<(?P<email>\S+)>)?$',s)
            if not mo:
                raise EAsciiDoc,'malformed author line'
            firstname = mo.group('name1')
            if mo.group('name3'):
                middlename = mo.group('name2')
                lastname = mo.group('name3')
            else:
                middlename = None
                lastname = mo.group('name2')
            email = mo.group('email')
            author = firstname
            initials = firstname[0]
            if middlename:
                author += ' '+middlename
                initials += middlename[0]
            if lastname:
                author += ' '+lastname
                initials += lastname[0]
            initials = string.upper(initials)
            if firstname: 
                gloss['firstname'] = config.subs_specialchars(firstname)
            if middlename: 
                gloss['middlename'] = config.subs_specialchars(middlename)
            if lastname: 
                gloss['lastname'] = config.subs_specialchars(lastname)
            if author: 
                gloss['author'] = config.subs_specialchars(author)
            if initials: 
                gloss['authorinitials'] = config.subs_specialchars(initials)
            if email: 
                gloss['email'] = email
            if reader.read_next():
                # Parse revision line.
                s = reader.read()
                s = subs_glossary([s])[0]
                # Match RCS/CVS $Id$ marker format.
                mo = re.match(r'^\$Id: \S+ (?P<revision>\S+)'
                    ' (?P<date>\S+) \S+ \S+ \S+ \$$',s)
                if not mo:
                    # Match AsciiDoc revision,date format.
                    mo = re.match(r'^\D*(?P<revision>.*?),(?P<date>.+)$',s)
                if mo:
                    revision = string.strip(mo.group('revision'))
                    date = string.strip(mo.group('date'))
                else:
                    revision = None
                    date = string.strip(s)
                if revision:
                    gloss['revision'] = revision
                if date:
                    gloss['date'] = date
        if document.backend == 'linuxdoc' and not gloss.has_key('author'):
            warning('linuxdoc requires author name')
        if document.doctype == 'manpage':
            # Translate mandatory NAME section.
            if Lex.next() is not Title:
                raise EAsciiDoc,'manpage must start with a NAME section'
            Title.parse()
            if Title.level != 1:
                raise EAsciiDoc,'manpage NAME section title must be level 1'
            if string.upper(Title.dict['title']) <> 'NAME':
                raise EAsciiDoc,'manpage must start with a NAME section'
            if not isinstance(Lex.next(),Paragraph):
                raise EAsciiDoc,'malformed manpage NAME section body'
            lines = reader.read_until(r'^$')
            s = string.join(lines)
            mo = re.match(r'^(?P<manname>.*?)-(?P<manpurpose>.*)$',s)
            if not mo:
                raise EAsciiDoc,'malformed manpage NAME section body'
            gloss['manname'] = string.strip(mo.group('manname'))
            gloss['manpurpose'] = string.strip(mo.group('manpurpose'))
    parse = staticmethod(parse)

class BlockTitle:
    '''Static methods and attributes only.'''
    title = None
    pattern = None
    def __init__(self):
        raise AssertionError,'no class instances allowed'
    def isnext():
        result = 0  # Assume failure.
        line = reader.read_next()
        if line:
            mo = re.match(BlockTitle.pattern,line)
            if mo:
                BlockTitle.title = mo.group('title')
                result = 1
        return result
    isnext = staticmethod(isnext)
    def translate():
        assert Lex.next() is BlockTitle
        reader.read()   # Discard title from reader.
        # Perform title substitutions.
        s = Lex.subs((BlockTitle.title,), Title.subs)
        s = string.join(s,writer.newline)
        if not s:
            warning('blank block title')
        BlockTitle.title = s
    translate = staticmethod(translate)
    def gettitle(dict):
        '''If there is a title add it to dict then reset title.'''
        if BlockTitle.title:
            dict['title'] = BlockTitle.title
            BlockTitle.title = None
    gettitle = staticmethod(gettitle)

class Title:
    '''Processes Header and Section titles. Static methods and attributes
    only.'''
    # Class variables
    underlines = ('==','--','~~','^^','++') # Levels 0,1,2,3,4.
    subs = ('specialcharacters','quotes','replacements','glossary','macros')
    pattern = r'^(?P<title>.*)$'
    title = None    # Raw unparsed title line.
    level = 0
    dict = {}
    sectname = None
    section_numbers = [0]*len(underlines)
    dump_dict = {}
    def __init__(self):
        raise AssertionError,'no class instances allowed'
    def parse():
        '''Parse the Title.dict and Title.level from the reader. The
        real work has already been done by isnext().'''
        assert Lex.next() is Title
        reader.read(); reader.read()    # Discard title from reader.
        Title.setsectname()
        # Perform title substitutions.
        s = Lex.subs((Title.dict['title'],), Title.subs)
        s = string.join(s,writer.newline)
        if not s:
            warning('blank section title')
        Title.dict['title'] = s
    parse = staticmethod(parse)
    def isnext():
        result = 0  # Assume failure.
        lines = reader.read_ahead(2)
        if len(lines) == 2:
            title = Lex.title_parse(lines)
            if title is not None:
                Title.title, Title.level = title
                Title.dict = re.match(Title.pattern,Title.title).groupdict()
                if Title.dict.has_key('args'):
                    parse_args(Title.dict['args'],Title.dict)
                if not Title.dict.has_key('title'):
                    warning('[titles] sectiontitle entry has no <title> group')
                    Title.dict['title'] = title
                for k,v in Title.dict.items():
                    if v is None: del Title.dict[k]
                result = 1
        return result
    isnext = staticmethod(isnext)
    def load(dict):
        '''Load and validate [titles] section entries from dict.'''
        if dict.has_key('underlines'):
            errmsg = 'malformed [titles] underlines entry'
            try:
                underlines = parse_list(dict['underlines'])
            except:
                raise EAsciiDoc,errmsg
            if len(underlines) != len(Title.underlines):
                raise EAsciiDoc,errmsg
            for s in underlines:
                if len(s) !=2:
                    raise EAsciiDoc,errmsg
            Title.underlines = tuple(underlines)
            Title.dump_dict['underlines'] = dict['underlines']
        if dict.has_key('subs'):
            Title.subs = parse_options(dict['subs'], SUBS_OPTIONS,
                'illegal [titles] subs entry')
            Title.dump_dict['subs'] = dict['subs']
        if dict.has_key('sectiontitle'):
            pat = dict['sectiontitle']
            if not pat or not is_regexp(pat):
                raise EAsciiDoc,'malformed [titles] sectiontitle entry'
            Title.pattern = pat
            Title.dump_dict['sectiontitle'] = pat
        if dict.has_key('blocktitle'):
            pat = dict['blocktitle']
            if not pat or not is_regexp(pat):
                raise EAsciiDoc,'malformed [titles] blocktitle entry'
            BlockTitle.pattern = pat
            Title.dump_dict['blocktitle'] = pat
    load = staticmethod(load)
    def dump():
        dump_section('titles',Title.dump_dict)
    dump = staticmethod(dump)
    def setsectname():
        '''Set Title section name. First search for section title in
        [specialsections], if not found use default 'sect<level>' name.'''
        for pat,sect in config.specialsections.items():
            mo = re.match(pat,Title.dict['title'])
            if mo:
                title = mo.groupdict().get('title')
                if title is not None:
                    Title.dict['title'] = string.strip(title)
                else:
                    Title.dict['title'] = string.strip(mo.group())
                Title.sectname = sect
                break
        else:
            Title.sectname = 'sect%d' % (Title.level,)
    setsectname = staticmethod(setsectname)
    def getnumber(level):
        '''Return next section number at section 'level' formatted like
        1.2.3.4.'''
        number = ''
        for l in range(len(Title.section_numbers)):
            n = Title.section_numbers[l]
            if l == 0:
                continue
            elif l < level:
                number = '%s%d.' % (number, n)
            elif l == level:
                number = '%s%d.' % (number, n + 1)
                Title.section_numbers[l] = n + 1
            elif l > level:
                # Reset unprocessed section levels.
                Title.section_numbers[l] = 0 
        return number
    getnumber = staticmethod(getnumber)


class Section:
    '''Static methods and attributes only.'''
    endtags = [] # Stack of currently open section (level,endtag) tuples.
    def __init__(self):
        raise AssertionError,'no class instances allowed'
    def savetag(level,etag):
        '''Save section end.'''
        Section.endtags.append((level,etag))
    savetag = staticmethod(savetag)
    def setlevel(level):
        '''Set document level and write open section close tags up to level.'''
        while Section.endtags and Section.endtags[-1][0] >= level:
            writer.write(Section.endtags.pop()[1])
        document.level = level
    setlevel = staticmethod(setlevel)
    def translate():
        assert Lex.next() is Title
        prev_sectname = Title.sectname
        Title.parse()
        if Title.level == 0 and document.doctype != 'book':
            raise EAsciiDoc,'only book doctypes can contain level 0 sections'
        if Title.level > document.level+1:
            # Sub-sections of multi-part book level zero Preface and Appendices
            # will be out of sequence so skip warning.
            if not (document.doctype == 'book' \
                    and document.level == 0 \
                    and Title.level == 2 \
                    and prev_sectname in ('sect-preface','sect-appendix') \
                    ):
                warning('section title out of sequence: '
                    'expected level %d, got level %d'
                    % (document.level+1, Title.level))
        Section.setlevel(Title.level)
        Title.dict['sectnum'] = Title.getnumber(document.level)
        stag,etag = config.section2tags(Title.sectname,Title.dict)
        Section.savetag(Title.level,etag)
        writer.write(stag)
        Section.translate_body()
    translate = staticmethod(translate)
    def translate_body(terminator=Title):
        isempty = 1
        next = Lex.next()
        while next and next is not terminator:
            if next is Title and isinstance(terminator,DelimitedBlock):
                raise EAsciiDoc,'title not permitted in sidebar body'
            if document.backend == 'linuxdoc'   \
                and document.level == 0         \
                and not isinstance(next,Paragraph):
                warning('only paragraphs are permitted in linuxdoc synopsis')
            next.translate()
            next = Lex.next()
            isempty = 0
        # The section is not empty if contains a subsection.
        if next and isempty and Title.level > document.level:
            isempty = 0
        # DocBook indexes can be empty.
        if isempty and Title.sectname != 'sect-index':
            warning('empty section: %s' % Title.title)
    translate_body = staticmethod(translate_body)

class Paragraphs:
    '''List of paragraph definitions.'''
    def __init__(self):
        self.current=None
        self.paragraphs = []    # List of Paragraph objects.
        self.default = None     # The default [paradef-default] paragraph.
    def load(self,sections):
        '''Update paragraphs defined in 'sections' dictionary.'''
        for k in sections.keys():
            if re.match(r'^paradef.+$',k):
                dict = {}
                parse_entries(sections.get(k,()),dict)
                for p in self.paragraphs:
                    if p.name == k: break
                else:
                    p = Paragraph()
                    self.paragraphs.append(p)
                try:
                    p.load(k,dict)
                except EAsciiDoc,e:
                    raise EAsciiDoc,'[%s] %s' % (k,str(e))
    def dump(self):
        for p in self.paragraphs:
            p.dump()
    def isnext(self):
        for p in self.paragraphs:
            if p.isnext():
                self.current = p
                return 1;
        return 0
    def check(self):
        # Check all paragraphs have valid delimiter.
        for p in self.paragraphs:
            if not p.delimiter or not is_regexp(p.delimiter):
                raise EAsciiDoc,'[%s] missing or illegal delimiter' % (p.name,)
        # Check all paragraph sections exist.
        for p in self.paragraphs:
            if not p.section:
                warning('[%s] missing section entry' % (p.name,))
            if not config.sections.has_key(p.section):
                warning('[%s] missing paragraph section' % (p.section,))
        # Check we have a default paragraph definition, put it last in list.
        for i in range(len(self.paragraphs)):
            if self.paragraphs[i].name == 'paradef-default':
                p = self.paragraphs[i]
                del self.paragraphs[i]
                self.paragraphs.append(p)
                self.default = p
                break
        else:
            raise EAsciiDoc,'missing [paradef-default] section'

class Paragraph:
    OPTIONS = ('listelement',)
    def __init__(self):
        self.name=None      # Configuration file section name.
        self.delimiter=None # Regular expression matching paragraph delimiter.
        self.section=None   # Name of section defining paragraph start/end tags.
        self.options=()     # List of paragraph option names.
        self.presubs=SUBS_DEFAULT   # List of pre-filter substitution option names.
        self.postsubs=()    # List of post-filter substitution option names.
        self.filter=None    # Executable paragraph filter command.
    def load(self,name,dict):
        '''Update paragraph definition from section entries in 'dict'.'''
        self.name = name
        for k,v in dict.items():
            if k == 'delimiter':
                if v and is_regexp(v):
                    self.delimiter = v
                else:
                    raise EAsciiDoc,'malformed paragraph delimiter "%s"' % (v,)
            elif k == 'section':
                if is_name(v):
                    self.section = v
                else:
                    raise EAsciiDoc,'malformed paragraph section name "%s"' \
                        % (v,)
            elif k == 'options':
                self.options = parse_options(v,Paragraph.OPTIONS,
                    'illegal Paragraph %s option' % (k,))
            elif k == 'presubs':
                self.presubs = parse_options(v,SUBS_OPTIONS,
                    'illegal Paragraph %s option' % (k,))
            elif k == 'postsubs':
                self.postsubs = parse_options(v,SUBS_OPTIONS,
                    'illegal Paragraph %s option' % (k,))
            elif k == 'filter':
                self.filter = v
            else:
                raise EAsciiDoc,'illegal paragraph parameter name "%s"' % (k,)
    def dump(self):
        write = lambda s: sys.stdout.write('%s%s' % (s,writer.newline))
        write('['+self.name+']')
        write('delimiter='+self.delimiter)
        if self.section:
            write('section='+self.section)
        if self.options:
            write('options='+string.join(self.options,','))
        if self.presubs:
            write('presubs='+string.join(self.presubs,','))
        if self.postsubs:
            write('postsubs='+string.join(self.postsubs,','))
        if self.filter:
            write('filter='+self.filter)
        write('')
    def isnext(self):
        reader.skip_blank_lines()
        if reader.read_next():
            return re.match(self.delimiter,reader.read_next())
        else:
            return 0
    def parse_delimiter_text(self):
        '''Return the text in the paragraph delimiter line.'''
        delimiter = reader.read()
        mo = re.match(self.delimiter,delimiter)
        assert mo
        result = mo.groupdict().get('text')
        if result is None:
            raise EAsciiDoc,'no text group in [%s] delimiter' % (self.name,)
        return result
    def write_body(self,body):
        dict = {}
        BlockTitle.gettitle(dict)
        stag,etag = config.section2tags(self.section,dict)
        # Writes blank line if the tag is empty (to separate LinuxDoc
        # paragraphs).
        if not stag: stag = ['']
        if not etag: etag = ['']
        writer.write(list(stag)+list(body)+list(etag))
    def translate(self):
        line1 = self.parse_delimiter_text()
        # The next line introduces the requirement that a List cannot
        # immediately follow a preceding Paragraph (introduced in v3.2.2).
        body = reader.read_until(r'^$|'+blocks.delimiter+r'|'+tables.delimiter)
        body = [line1] + list(body)
        body = join_lines(body)
        body = Lex.set_margin(body) # Move body to left margin.
        body = Lex.subs(body,self.presubs)
        if self.filter:
            body = filter_lines(self.filter,body)
        body = Lex.subs(body,self.postsubs)
        self.write_body(body)
    
class Lists:
    '''List of List objects.'''
    def __init__(self):
        self.current=None
        self.lists = []     # List objects.
        self.delimiter = '' # Combined blocks delimiter regular expression.
        self.open = []      # A stack of the current an parent lists.
    def load(self,sections):
        '''Update lists defined in 'sections' dictionary.'''
        for k in sections.keys():
            if re.match(r'^listdef.+$',k):
                dict = {}
                parse_entries(sections.get(k,()),dict)
                for l in self.lists:
                    if l.name == k: break
                else:
                    l = List()  # Create a new list if it doesn't exist.
                    self.lists.append(l)
                try:
                    l.load(k,dict)
                except EAsciiDoc,e:
                    raise EAsciiDoc,'[%s] %s' % (k,str(e))
    def dump(self):
        for l in self.lists:
            l.dump()
    def isnext(self):
        for l in self.lists:
            if l.isnext():
                self.current = l
                return 1;
        return 0
    def check(self):
        for l in self.lists:
            # Check list has valid type .
            if not l.type in l.TYPES:
                raise EAsciiDoc,'[%s] illegal type' % (l.name,)
            # Check list has valid delimiter.
            if not l.delimiter or not is_regexp(l.delimiter):
                raise EAsciiDoc,'[%s] missing or illegal delimiter' % (l.name,)
            # Check all list tags.
            if not l.listtag or not config.tags.has_key(l.listtag):
                warning('[%s] missing listtag' % (l.name,))
            if not l.itemtag or not config.tags.has_key(l.itemtag):
                warning('[%s] missing tag itemtag' % (l.name,))
            if not l.texttag or not config.tags.has_key(l.texttag):
                warning('[%s] missing tag texttag' % (l.name,))
            if l.type == 'variable':
                if not l.entrytag or not config.tags.has_key(l.entrytag):
                    warning('[%s] missing entrytag' % (l.name,))
                if not l.termtag or not config.tags.has_key(l.termtag):
                    warning('[%s] missing termtag' % (l.name,))
        # Build combined lists delimiter pattern.
        delimiters = []
        for l in self.lists:
            delimiters.append(l.delimiter)
        self.delimiter = join_regexp(delimiters)

class List:
    TAGS = ('listtag','itemtag','texttag','entrytag','termtag')
    TYPES = ('simple','variable')
    def __init__(self):
        self.name=None      # List definition configuration file section name.
        self.type=None      # 'simple' or 'variable'
        self.delimiter=None # Regular expression matching list item delimiter.
        self.subs=SUBS_DEFAULT  # List of substitution option names.
        self.listtag=None
        self.itemtag=None
        self.texttag=None   # Tag for list item text.
        self.termtag=None   # Variable lists only.
        self.entrytag=None  # Variable lists only.
    def load(self,name,dict):
        '''Update block definition from section entries in 'dict'.'''
        self.name = name
        for k,v in dict.items():
            if k == 'type':
                if v in self.TYPES:
                    self.type = v
                else:
                    raise EAsciiDoc,'illegal list type "%s"' % (v,)
            elif k == 'delimiter':
                if v and is_regexp(v):
                    self.delimiter = v
                else:
                    raise EAsciiDoc,'malformed list delimiter "%s"' % (v,)
            elif k == 'subs':
                self.subs = parse_options(v,SUBS_OPTIONS,
                    'illegal List %s option' % (k,))
            elif k in self.TAGS:
                if is_name(v):
                    setattr(self,k,v)
                else:
                    raise EAsciiDoc,'illegal list %s name "%s"' % (k,v)
            else:
                raise EAsciiDoc,'illegal list parameter name "%s"' % (k,)
    def dump(self):
        write = lambda s: sys.stdout.write('%s%s' % (s,writer.newline))
        write('['+self.name+']')
        write('type='+self.type)
        write('delimiter='+self.delimiter)
        if self.subs:
            write('subs='+string.join(self.subs,','))
        write('listtag='+self.listtag)
        write('itemtag='+self.itemtag)
        write('texttag='+self.texttag)
        if self.type == 'variable':
            write('entrytag='+self.entrytag)
            write('termtag='+self.termtag)
        write('')
    def isnext(self):
        reader.skip_blank_lines()
        if reader.read_next():
            return re.match(self.delimiter,reader.read_next())
        else:
            return 0
    def parse_delimiter_text(self):
        '''Return the text in the list delimiter line.'''
        delimiter = reader.read()
        mo = re.match(self.delimiter,delimiter)
        assert mo
        result = mo.groupdict().get('text')
        if result is None:
            raise EAsciiDoc,'no text group in [%s] delimiter' % (self.name,)
        return result
    def translate_entry(self):
        assert self.type == 'variable'
        stag,etag = config.tag(self.entrytag)
        if stag: writer.write(stag)
        # Write terms.
        while Lex.next() is self:
            term = self.parse_delimiter_text()
            writer.write_tag(self.termtag,[term],self.subs)
        # Write definition.
        self.translate_item()
        if etag: writer.write(etag)
    def translate_item(self,first_line=None):
        stag,etag = config.tag(self.itemtag)
        if stag: writer.write(stag)
        # Write ItemText.
        text = reader.read_until(lists.delimiter+'|^$|'+blocks.delimiter \
            +r'|'+tables.delimiter)
        if first_line is not None:
            text = [first_line] + list(text)
        text = join_lines(text)
        writer.write_tag(self.texttag,text,self.subs)
        # Process nested ListParagraphs and Lists.
        while 1:
            next = Lex.next()
            if next in lists.open:
                break
            elif isinstance(next,List):
                next.translate()
            elif isinstance(next,Paragraph) and 'listelement' in next.options:
                next.translate()
            else:
                break
        if etag: writer.write(etag)
    def translate(self):
        lists.open.append(self)
        stag,etag = config.tag(self.listtag)
        if stag:
            dict = {}
            BlockTitle.gettitle(dict)
            stag = subs_glossary([stag],dict)[0]
            writer.write(stag)
        while Lex.next() is self:
            if self.type == 'simple':
                first_line = self.parse_delimiter_text()
                self.translate_item(first_line)
            elif self.type == 'variable':
                self.translate_entry()
            else:
                raise AssertionError,'illegal [%s] list type"' % (self.name,)
        if etag:
            writer.write(etag)
        lists.open.pop()


class DelimitedBlocks:
    '''List of delimited blocks.'''
    def __init__(self):
        self.current=None
        self.blocks = []    # List of DelimitedBlock objects.
        self.delimiter = '' # Combined blocks delimiter regular expression.
    def load(self,sections):
        '''Update blocks defined in 'sections' dictionary.'''
        for k in sections.keys():
            if re.match(r'^blockdef.+$',k):
                dict = {}
                parse_entries(sections.get(k,()),dict)
                for b in self.blocks:
                    if b.name == k: break
                else:
                    b = DelimitedBlock()
                    self.blocks.append(b)
                try:
                    b.load(k,dict)
                except EAsciiDoc,e:
                    raise EAsciiDoc,'[%s] %s' % (k,str(e))
    def dump(self):
        for b in self.blocks:
            b.dump()
    def isnext(self):
        for b in self.blocks:
            if b.isnext():
                self.current = b
                return 1;
        return 0
    def check(self):
        # Check all blocks have valid delimiter.
        for b in self.blocks:
            if not b.delimiter or not is_regexp(b.delimiter):
                raise EAsciiDoc,'[%s] missing or illegal delimiter' % (b.name,)
        # Check all block sections exist.
        for b in self.blocks:
            if 'skip' not in b.options:
                if not b.section:
                    warning('[%s] missing section entry' % (b.name,))
                if not config.sections.has_key(b.section):
                    warning('[%s] missing block section' % (b.section,))
        # Build combined block delimiter pattern.
        delimiters = []
        for b in self.blocks:
            delimiters.append(b.delimiter)
        self.delimiter = join_regexp(delimiters)

class DelimitedBlock:
    OPTIONS = ('section','skip','argsline')
    def __init__(self):
        self.name=None      # Block definition configuration file section name.
        self.delimiter=None # Regular expression matching block delimiter.
        self.section=None   # Name of section defining block header/footer.
        self.options=()     # List of block option names.
        self.presubs=()     # List of pre-filter substitution option names.
        self.postsubs=()    # List of post-filter substitution option names.
        self.filter=None    # Executable block filter command.
    def load(self,name,dict):
        '''Update block definition from section entries in 'dict'.'''
        self.name = name
        for k,v in dict.items():
            if k == 'delimiter':
                if v and is_regexp(v):
                    self.delimiter = v
                else:
                    raise EAsciiDoc,'malformed block delimiter "%s"' % (v,)
            elif k == 'section':
                if is_name(v):
                    self.section = v
                else:
                    raise EAsciiDoc,'malformed block section name "%s"' % (v,)
            elif k == 'options':
                self.options = parse_options(v,DelimitedBlock.OPTIONS,
                    'illegal DelimitedBlock %s option' % (k,))
            elif k == 'presubs':
                self.presubs = parse_options(v,SUBS_OPTIONS,
                    'illegal DelimitedBlock %s option' % (k,))
            elif k == 'postsubs':
                self.postsubs = parse_options(v,SUBS_OPTIONS,
                    'illegal DelimitedBlock %s option' % (k,))
            elif k == 'filter':
                self.filter = v
            else:
                raise EAsciiDoc,'illegal block parameter name "%s"' % (k,)
    def dump(self):
        write = lambda s: sys.stdout.write('%s%s' % (s,writer.newline))
        write('['+self.name+']')
        write('delimiter='+self.delimiter)
        if self.section:
            write('section='+self.section)
        if self.options:
            write('options='+string.join(self.options,','))
        if self.presubs:
            write('presubs='+string.join(self.presubs,','))
        if self.postsubs:
            write('postsubs='+string.join(self.postsubs,','))
        if self.filter:
            write('filter='+self.filter)
        write('')
    def isnext(self):
        reader.skip_blank_lines()
        if reader.read_next():
            return re.match(self.delimiter,reader.read_next())
        else:
            return 0
    def translate(self):
        dict = {}
        BlockTitle.gettitle(dict)
        delimiter = reader.read()
        mo = re.match(self.delimiter,delimiter)
        assert mo
        dict.update(mo.groupdict())
        for k,v in dict.items():
            if v is None: del dict[k]
        if dict.has_key('args'):
            # Extract embedded arguments from leading delimiter line.
            parse_args(dict['args'],dict)
        elif 'argsline' in self.options:
            # Parse block arguments line.
            reader.parse_arguments(dict)
        # Process block contents.
        if 'skip' in self.options:
            # Discard block body.
            reader.read_until(self.delimiter,same_file=1)
        elif 'section' in self.options:
            stag,etag = config.section2tags(self.section,dict)
            # The body is treated like a SimpleSection.
            writer.write(stag)
            Section.translate_body(self)
            writer.write(etag)
        else:
            stag,etag = config.section2tags(self.section,dict)
            body = reader.read_until(self.delimiter,same_file=1)
            body = Lex.subs(body,self.presubs)
            if self.filter:
                body = filter_lines(self.filter,body,dict)
            body = Lex.subs(body,self.postsubs)
            # Write start tag, content, end tag.
            writer.write(list(stag)+list(body)+list(etag))
        if reader.eof():
            raise EAsciiDoc,'closing [%s] delimiter expected' % (self.name,)
        delimiter = reader.read()   # Discard delimiter line.
        assert re.match(self.delimiter,delimiter)
    

class Tables:
    '''List of tables.'''
    def __init__(self):
        self.current=None
        self.tables = []    # List of Table objects.
        self.delimiter = '' # Combined tables delimiter regular expression.
    def load(self,sections):
        '''Update tables defined in 'sections' dictionary.'''
        for k in sections.keys():
            if re.match(r'^tabledef.+$',k):
                dict = {}
                parse_entries(sections.get(k,()),dict)
                for t in self.tables:
                    if t.name == k: break
                else:
                    t = Table()
                    self.tables.append(t)
                try:
                    t.load(k,dict)
                except EAsciiDoc,e:
                    raise EAsciiDoc,'[%s] %s' % (k,str(e))
    def dump(self):
        for t in self.tables:
            t.dump()
    def isnext(self):
        for t in self.tables:
            if t.isnext():
                self.current = t
                return 1;
        return 0
    def check(self):
        # Check we have a default table definition,
        for i in range(len(self.tables)):
            if self.tables[i].name == 'tabledef-default':
                default = self.tables[i]
                break
        else:
            raise EAsciiDoc,'missing [table-default] section'
        # Set default table defaults.
        if default.subs is None: default.subs = SUBS_DEFAULT
        if default.format is None: default.subs = 'fixed'
        # Propagate defaults to unspecified table parameters.
        for t in self.tables:
            if t is not default:
                if t.fillchar is None: t.fillchar = default.fillchar
                if t.subs is None: t.subs = default.subs
                if t.format is None: t.format = default.format
                if t.section is None: t.section = default.section
                if t.colspec is None: t.colspec = default.colspec
                if t.headrow is None: t.headrow = default.headrow
                if t.footrow is None: t.footrow = default.footrow
                if t.bodyrow is None: t.bodyrow = default.bodyrow
                if t.headdata is None: t.headdata = default.headdata
                if t.footdata is None: t.footdata = default.footdata
                if t.bodydata is None: t.bodydata = default.bodydata
        # Check all tables have valid fill character.
        for t in self.tables:
            if not t.fillchar or len(t.fillchar) != 1:
                raise EAsciiDoc,'[%s] missing or illegal fillchar' % (t.name,)
        # Build combined tables delimiter patterns and assign defaults.
        delimiters = []
        for t in self.tables:
            # Ruler is:
            #   (ColStop,(ColWidth,FillChar+)?)+, FillChar+, TableWidth?
            t.delimiter = r'^(' + Table.COL_STOP \
                + r'(\d*|' + re.escape(t.fillchar) + r'*)' \
                + r')+' \
                + re.escape(t.fillchar) + r'+' \
                + '([\d\.]*)$'
            delimiters.append(t.delimiter)
            if not t.headrow:
                t.headrow = t.bodyrow
            if not t.footrow:
                t.footrow = t.bodyrow
            if not t.headdata:
                t.headdata = t.bodydata
            if not t.footdata:
                t.footdata = t.bodydata
        self.delimiter = join_regexp(delimiters)
        # Check table definitions are valid.
        for t in self.tables:
            t.check()
            if t.check_msg:
                warning('[%s] table definition: %s' % (t.name,t.check_msg))

class Column:
    '''Table column.'''
    def __init__(self):
        self.colalign = None    # 'left','right','center'
        self.rulerwidth = None
        self.colwidth = None    # Output width in page units.

class Table:
    COL_STOP = r"(`|'|\.)"  # RE.
    ALIGNMENTS = {'`':'left', "'":'right', '.':'center'}
    FORMATS = ('fixed','csv','dsv')
    def __init__(self):
        # Configuration parameters.
        self.name=None      # Table definition configuration file section name.
        self.fillchar=None
        self.subs=None
        self.format=None    # 'fixed','csv','dsv'
        self.section=None
        self.colspec=None
        self.headrow=None
        self.footrow=None
        self.bodyrow=None
        self.headdata=None
        self.footdata=None
        self.bodydata=None
        # Calculated parameters.
        self.delimiter=None # RE matching any table ruler.
        self.underline=None # RE matching current table underline.
        self.isnumeric=0    # True if numeric ruler, false if character ruler.
        self.tablewidth=None # Optional table width scale factor.
        self.columns=[]     # List of Columns.
        self.dict={}        # Substitutions dictionary.
        # Other.
        self.check_msg=''   # Message set by previous self.check() call.
    def load(self,name,dict):
        '''Update table definition from section entries in 'dict'.'''
        self.name = name
        for k,v in dict.items():
            if k == 'fillchar':
                if v and len(v) == 1:
                    self.fillchar = v
                else:
                    raise EAsciiDoc,'malformed table fillchar "%s"' % (v,)
            elif k == 'section':
                if is_name(v):
                    self.section = v
                else:
                    raise EAsciiDoc,'malformed table section name "%s"' % (v,)
            elif k == 'subs':
                self.subs = parse_options(v,SUBS_OPTIONS,
                    'illegal Table %s option' % (k,))
            elif k == 'format':
                if v in Table.FORMATS:
                    self.format = v
                else:
                    raise EAsciiDoc,'illegal table format "%s"' % (v,)
            elif k == 'colspec':
                self.colspec = v
            elif k == 'headrow':
                self.headrow = v
            elif k == 'footrow':
                self.footrow = v
            elif k == 'bodyrow':
                self.bodyrow = v
            elif k == 'headdata':
                self.headdata = v
            elif k == 'footdata':
                self.footdata = v
            elif k == 'bodydata':
                self.bodydata = v
            else:
                raise EAsciiDoc,'illegal table parameter name "%s"' % (k,)
    def dump(self):
        write = lambda s: sys.stdout.write('%s%s' % (s,writer.newline))
        write('['+self.name+']')
        write('fillchar='+self.fillchar)
        write('subs='+string.join(self.subs,','))
        write('format='+self.format)
        write('section='+self.section)
        if self.colspec:
            write('colspec='+self.colspec)
        if self.headrow:
            write('headrow='+self.headrow)
        if self.footrow:
            write('footrow='+self.footrow)
        write('bodyrow='+self.bodyrow)
        if self.headdata:
            write('headdata='+self.headdata)
        if self.footdata:
            write('footdata='+self.footdata)
        write('bodydata='+self.bodydata)
        write('')
    def check(self):
        '''Check table definition and set self.check_msg if invalid else set
        self.check_msg to blank string.'''
        # Check global table parameters.
        if config.textwidth is None:
            self.check_msg = 'missing [miscellaneous] textwidth entry'
        elif config.pagewidth is None:
            self.check_msg = 'missing [miscellaneous] pagewidth entry'
        elif config.pageunits is None:
            self.check_msg = 'missing [miscellaneous] pageunits entry'
        elif not self.section:
            self.check_msg = 'missing section entry'
        elif not config.sections.has_key(self.section):
            self.check_msg = 'missing section %s' % (self.section,)
        elif self.headrow is None:
            self.check_msg = 'missing headrow entry'
        elif self.footrow is None:
            self.check_msg = 'missing footrow entry'
        elif self.bodyrow is None:
            self.check_msg = 'missing bodyrow entry'
        elif self.headdata is None:
            self.check_msg = 'missing headdata entry'
        elif self.footdata is None:
            self.check_msg = 'missing footdata entry'
        elif self.bodydata is None:
            self.check_msg = 'missing bodydata entry'
        else:
            # No errors.
            self.check_msg = ''

    def isnext(self):
        reader.skip_blank_lines()
        if reader.read_next():
            return re.match(self.delimiter,reader.read_next())
        else:
            return 0
    def parse_ruler(self,ruler):
        '''Parse ruler calculating underline and ruler column widths.'''
        fc = re.escape(self.fillchar)
        # Strip and save optional tablewidth from end of ruler.
        mo = re.match(r'^(.*'+fc+r'+)([\d\.]+)$',ruler)
        if mo:
            ruler = mo.group(1)
            self.tablewidth = float(mo.group(2))
            self.dict['tablewidth'] = str(float(self.tablewidth))
        else:
            self.tablewidth = None
            self.dict['tablewidth'] = '100.0'
        # Guess whether column widths are specified numerically or not.
        if ruler[1] != self.fillchar:
            # If the first column does not start with a fillchar then numeric.
            self.isnumeric = 1
        elif ruler[1:] == self.fillchar*len(ruler[1:]):
            # The case of one column followed by fillchars is numeric.
            self.isnumeric = 1
        else:
            self.isnumeric = 0
        # Underlines must be 3 or more fillchars.
        self.underline = r'^' + fc + r'{3,}$'
        splits = re.split(self.COL_STOP,ruler)[1:]
        # Build self.columns.
        for i in range(0,len(splits),2):
            c = Column()
            c.colalign = self.ALIGNMENTS[splits[i]]
            s = splits[i+1]
            if self.isnumeric:
                # Strip trailing fillchars.
                s = re.sub(fc+r'+$','',s)
                if s == '':
                    c.rulerwidth = None
                else:
                    c.rulerwidth = int(validate(s,'int($)>0',
                        'malformed ruler: bad width'))
            else:   # Calculate column width from inter-fillchar intervals.
                if not re.match(r'^'+fc+r'+$',s):
                    raise EAsciiDoc,'malformed ruler: illegal fillchars'
                c.rulerwidth = len(s)+1
            self.columns.append(c)
        # Fill in unspecified ruler widths.
        if self.isnumeric:
            if self.columns[0].rulerwidth is None:
                prevwidth = 1
            for c in self.columns:
                if c.rulerwidth is None:
                    c.rulerwidth = prevwidth
                prevwidth = c.rulerwidth
    def build_colspecs(self):
        '''Generate colwidths and colspecs. This can only be done after the
        table arguments have been parsed since we use the table format.'''
        self.dict['cols'] = len(self.columns)
        # Calculate total ruler width.
        totalwidth = 0
        for c in self.columns:
            totalwidth = totalwidth + c.rulerwidth
        if totalwidth <= 0:
            raise EAsciiDoc,'zero width table'
        # Calculate marked up colwidths from rulerwidths.
        for c in self.columns:
            # Convert ruler width to output page width.
            width = float(c.rulerwidth)
            if self.format == 'fixed':
                if self.tablewidth is None:
                    # Size proportional to ruler width.
                    colfraction = width/config.textwidth
                else:
                    # Size proportional to page width.
                    colfraction = width/totalwidth
            else:
                    # Size proportional to page width.
                colfraction = width/totalwidth
            c.colwidth = colfraction * config.pagewidth # To page units.
            if self.tablewidth is not None:
                c.colwidth = c.colwidth * self.tablewidth   # Scale factor.
                if self.tablewidth > 1:
                    c.colwidth = c.colwidth/100 # tablewidth is in percent.
        # Build colspecs.
        if self.colspec:
            s = []
            for c in self.columns:
                self.dict['colalign'] = c.colalign
                self.dict['colwidth'] = str(int(c.colwidth))
                s.append(subs_glossary((self.colspec,),self.dict)[0])
            self.dict['colspecs'] = string.join(s,writer.newline)
    def parse_arguments(self):
        '''Parse table arguments string.'''
        d = {}
        reader.parse_arguments(d)
        # Update table with overridable parameters.
        if d.has_key('subs'):
            self.subs = parse_options(d['subs'],SUBS_OPTIONS,
                'illegal table subs %s option' % ('subs',))
        if d.has_key('format'):
            self.format = d['format']
        if d.has_key('tablewidth'):
            self.tablewidth = float(d['tablewidth'])
        # Add arguments to markup substitutions.
        self.dict.update(d)
    def split_rows(self,rows):
        '''Return a two item tuple containing a list of lines up to but not
        including the next underline (continued lines are joined ) and the
        tuple of all lines after the underline.'''
        reo = re.compile(self.underline)
        i = 0
        while not reo.match(rows[i]):
            i = i+1
        if i == 0:
            raise EAsciiDoc,'missing [%s] table rows' % (self.name,)
        if i >= len(rows):
            raise EAsciiDoc,'closing [%s] underline expected' % (self.name,)
        return (join_lines(rows[:i]), rows[i+1:])
    def parse_rows(self, rows, rtag, dtag):
        '''Parse rows list using the row and data tags. Returns a substituted
        list of output lines.'''
        result = []
        # Source rows are parsed as single block, rather than line by line, to
        # allow the CSV reader to handle multi-line rows.
        if self.format == 'fixed':
            rows = self.parse_fixed(rows)
        elif self.format == 'csv':
            rows = self.parse_csv(rows)
        elif self.format == 'dsv':
            rows = self.parse_dsv(rows)
        else:
            assert 1,'illegal table format'
        # Substitute and indent all data in all rows.
        stag,etag = subs_tag(rtag,self.dict)
        for row in rows:
            result.append('  '+stag)
            for data in self.subs_row(row,dtag):
                result.append('    '+data)
            result.append('  '+etag)
        return result
    def subs_row(self, data, dtag):
        '''Substitute the list of source row data elements using the data tag.
        Returns a substituted list of output table data items.'''
        result = []
        if len(data) < len(self.columns):
            warning('fewer row data items then table columns')
        if len(data) > len(self.columns):
            warning('more row data items than table columns')
        for i in range(len(self.columns)):
            if i > len(data) - 1:
                d = ''  # Fill missing column data with blanks.
            else:
                d = data[i]
            c = self.columns[i]
            self.dict['colalign'] = c.colalign
            self.dict['colwidth'] = str(int(c.colwidth)) + config.pageunits
            stag,etag = subs_tag(dtag,self.dict)
            # Insert AsciiDoc line break (' +') where row data has newlines
            # ('\n').  This is really only useful when the table format is csv
            # and the output markup is HTML. It's also a bit dubious in that it
            # assumes the user has not modified the shipped line break pattern.
            if 'replacements' in self.subs:
                # Insert line breaks in cell data.
                d = re.sub(r'(?m)\n',r' +\n',d) 
                d = string.split(d,'\n')    # So writer.newline is written.
            else:
                d = [d]
            result = result + [stag] + Lex.subs(d,self.subs) + [etag]
        return result
    def parse_fixed(self,rows):
        '''Parse the list of source table rows. Each row item in the returned
        list contains a list of cell data elements.'''
        result = []
        for row in rows:
            data = []
            start = 0
            for c in self.columns:
                end = start + c.rulerwidth
                if c is self.columns[-1]:
                    # Text in last column can continue forever.
                    data.append(string.strip(row[start:]))
                else:
                    data.append(string.strip(row[start:end]))
                start = end
            result.append(data)
        return result
    def parse_csv(self,rows):
        '''Parse the list of source table rows. Each row item in the returned
        list contains a list of cell data elements.'''
        import StringIO
        try:
            import csv
        except:
            raise EAsciiDoc,'python 2.3 or better required to parse csv tables'
        result = []
        rdr = csv.reader(StringIO.StringIO(string.join(rows,'\r\n')),
            skipinitialspace=1)
        try:
            for row in rdr:
                result.append(row)
        except:
            raise EAsciiDoc,'csv parse error "%s"' % (row,)
        return result
    def parse_dsv(self,rows):
        '''Parse the list of source table rows. Each row item in the returned
        list contains a list of cell data elements.'''
        separator = self.dict.get('separator',':')
        separator = eval('"'+separator+'"')
        if len(separator) != 1:
            raise EAsciiDoc,'malformed dsv separator: %s' % (separator,)
        # TODO If separator is preceeded by an odd number of backslashes then
        # it is escaped and should not delimit.
        result = []
        for row in rows:
            # Skip blank lines
            if row == '': continue
            # Unescape escaped characters.
            row = eval('"'+string.replace(row,'"','\\"')+'"')
            data = string.split(row,separator)
            result.append(data)
        return result
    def translate(self):
        # Reset instance specific properties.
        self.underline = None
        self.columns = []
        self.dict = {}
        BlockTitle.gettitle(self.dict)
        # Add relevant globals to table substitutions.
        self.dict['pagewidth'] = str(config.pagewidth)
        self.dict['pageunits'] = config.pageunits
        # Save overridable table parameters.
        save_subs = self.subs
        save_format = self.format
        # Parse table ruler.
        ruler = reader.read()
        assert re.match(self.delimiter,ruler)
        self.parse_ruler(ruler)
        # Parse table arguments.
        self.parse_arguments()
        # Read the entire table.
        table = []
        while 1:
            line = reader.read_next()
            # Table terminated by underline followed by a blank line or EOF.
            if len(table) > 0 and re.match(self.underline,table[-1]):
                if line in ('',None):
                    break;
            if line is None:
                raise EAsciiDoc,'closing [%s] underline expected' % (self.name,)
            table.append(reader.read())
        if self.check_msg:  # Skip if table definition was marked invalid.
            warning('skipping %s table: %s' % (self.name,self.check_msg))
            return
        # Generate colwidths and colspecs.
        self.build_colspecs()
        # Generate headrows, footrows, bodyrows.
        headrows = footrows = []
        bodyrows,table = self.split_rows(table)
        if table:
            headrows = bodyrows
            bodyrows,table = self.split_rows(table)
            if table:
                footrows,table = self.split_rows(table)
        if headrows:
            headrows = self.parse_rows(headrows, self.headrow, self.headdata)
            self.dict['headrows'] = string.join(headrows,writer.newline)
        if footrows:
            footrows = self.parse_rows(footrows, self.footrow, self.footdata)
            self.dict['footrows'] = string.join(footrows,writer.newline)
        bodyrows = self.parse_rows(bodyrows, self.bodyrow, self.bodydata)
        self.dict['bodyrows'] = string.join(bodyrows,writer.newline)
        table = subs_glossary(config.sections[self.section],self.dict)
        writer.write(table)
        # Restore overridable table parameters.
        self.subs = save_subs
        self.format = save_format
    

class Macros:
    def __init__(self):
        self.macros = []        # List of Macros.
        self.current = None     # The last matched block macro.
    def load(self,entries):
        for entry in entries:
            m = Macro()
            m.load(entry)
            if m.name is None:
                # Delete undefined macro.
                for i in range(len(self.macros)-1,-1,-1):
                    if self.macros[i].pattern == m.pattern:
                        del self.macros[i]
            else:
                # Check for duplicates.
                for m2 in self.macros:
                    if m.equals(m2):
                        warning('duplicate macro: '+entry)
                        break
                else:
                    self.macros.append(m)
    def dump(self):
        write = lambda s: sys.stdout.write('%s%s' % (s,writer.newline))
        write('[macros]')
        for m in self.macros:
            write('%s=%s%s' % (m.pattern,m.prefix,m.name))
        write('')
    def check(self):
        # Check all named sections exist.
        for m in self.macros:
            if m.name and m.prefix != '+':
                m.section_name()
    def subs(self,text,prefix=''):
        result = text
        for m in self.macros:
            if m.prefix == prefix:
                result = m.subs(result)
        return result
    def isnext(self):
        '''Return matching macro if block macro is next on reader.'''
        reader.skip_blank_lines()
        line = reader.read_next()
        if line:
            for m in self.macros:
                if m.prefix == '#':
                    if m.reo.match(line):
                        self.current = m
                        return m
        return 0
    def match(self,prefix,name,text):
        '''Return re match object matching 'text' with macro type 'prefix',
        macro name 'name'.'''
        for m in self.macros:
            if m.prefix == prefix:
                mo = m.reo.match(text)
                if mo:
                    if m.name == name:
                        return mo
                    if re.match(name,mo.group('name')):
                        return mo
        return None

# Macro set just prior to calling _subs_macro(). Ugly but there's no way
# to pass optional arguments with _subs_macro().
_macro = None

def _subs_macro(mo):
    '''Function called to perform inline macro substitution. Uses matched macro
    regular expression object and returns string containing the substituted
    macro body. Called by Macros().subs().'''
    # Check if macro reference is escaped.
    if mo.group()[0] == '\\':
        return mo.group()[1:]   # Strip leading backslash.
    dict = mo.groupdict()
    # Delete groups that didn't participate in match.
    for k,v in dict.items():
        if v is None: del dict[k]
    if _macro.name:
        name = _macro.name
    else:
        if not dict.has_key('name'):
            warning('missing macro name group: %s' % (mo.re.pattern,))
            return ''
        name = dict['name']
    section_name = _macro.section_name(name)
    if not section_name:
        return ''
    # If we're dealing with a block macro get optional block title.
    if _macro.prefix == '#':
        BlockTitle.gettitle(dict)
    # Parse macro caption to macro arguments.
    if dict.has_key('caption'):
        if dict['caption'] in (None,''):
            del dict['caption']
        else:
            parse_args(dict['caption'],dict)
    body = config.subs_section(section_name,dict)
    if len(body) == 0:
        result = ''
    elif len(body) == 1:
        result = body[0]
    else:
        result = string.join(body,writer.newline)
    return result

class Macro:
    def __init__(self):
        self.pattern = None     # Matching regular expression.
        self.name = ''          # Conf file section name (None if implicit).
        self.prefix = ''        # '' if inline, '+' if builtin, '#' if block.
        self.reo = None         # Compiled pattern re object.
    def section_name(self,name=None):
        '''Return macro section name based on macro name and prefix.
        Return None section not found.'''
        assert self.prefix != '+'
        if not name:
            assert self.name
            name = self.name
        if self.prefix == '#':
            suffix = '-blockmacro'
        else:
            suffix = '-inlinemacro'
        if name == 'icon':
            warning('icon macro has been deprecated in favor of image macro')
            return name
        elif name == 'graphic':
            warning('graphic macro has been deprecated in favor of image macro')
            return name
        elif config.sections.has_key(name):
            warning('deprecated macro section name: [%s] (rename to [%s])'
                    % (name,name+suffix))
            return name
        elif config.sections.has_key(name+suffix):
            return name+suffix
        else:
            warning('missing macro section: [%s]' % (name+suffix,))
            return None
    def equals(self,m):
        if self.pattern != m.pattern:
            return 0
        if self.name != m.name:
            return 0
        if self.prefix != m.prefix:
            return 0
        return 1
    def load(self,entry):
        e = parse_entry(entry)
        if not e:
            raise EAsciiDoc,'malformed macro entry "%s"' % (entry,)
        self.pattern, self.name = e
        if not is_regexp(self.pattern):
            raise EAsciiDoc,'illegal regular expression in macro entry "%s"' \
                % (entry,)
        self.reo = re.compile(self.pattern)
        if self.name:
            if self.name[0] in ('+','#'):
                self.prefix, self.name = self.name[0], self.name[1:]
        if self.name and not is_name(self.name):
            raise EAsciiDoc,'illegal section name in macro entry "%s"' % \
                (entry,)
    def subs(self,text):
        global _macro
        _macro = self   # Pass the macro to _subs_macro().
        return self.reo.sub(_subs_macro,text)
    def translate(self):
        '''Translate block macro at reader.'''
        assert self.prefix == '#'
        line = reader.read()
        writer.write(self.subs(line))

#---------------------------------------------------------------------------
# Input stream Reader and output stream writer classes.
#---------------------------------------------------------------------------

class Reader1:
    '''Line oriented AsciiDoc input file reader. Processes non lexical
    entities: transparently handles included files. Tabs are expanded and lines
    are right trimmed.'''
    # This class is not used directly, use Reader class instead.
    READ_BUFFER_MIN = 10            # Read buffer low level.
    def __init__(self):
        self.f = None           # Input file object.
        self.fname = None       # Input file name.
        self.next = []          # Read ahead buffer containing
                                # (filename,linenumber,linetext) tuples.
        self.cursor = None      # Last read() (filename,linenumber,linetext).
        self.tabsize = 8        # Tab expansion number of spaces.
        self.parent = None      # Included reader's parent reader.
        self._lineno = 0        # The last line read from file object f.
        self.include_enabled = 1 # Enables/disables file inclusion.
        self.include_depth = 0  # Current include depth.
        self.include_max = 5    # Maxiumum allowed include depth.
    def open(self,fname):
        self.fname = fname
        verbose('reading: '+fname)
        if fname == '<stdin>':
            self.f = sys.stdin
        else:
            self.f = open(fname,"rb")
        self._lineno = 0            # The last line read from file object f.
        self.next = []
        # Prefill buffer by reading the first line and then pushing it back.
        if Reader1.read(self):
            self.unread(self.cursor)
            self.cursor = None
    def closefile(self):
        '''Used by class methods to close nested include files.'''
        self.f.close()
        self.next = []
    def close(self):
        self.closefile()
        self.__init__()
    def read(self):
        '''Read next line. Return None if EOF. Expand tabs. Strip trailing
        white space.  Maintain self.next read ahead buffer.'''
        # Top up buffer.
        if len(self.next) <= self.READ_BUFFER_MIN:
            s = self.f.readline()
            if s:
                self._lineno = self._lineno + 1
            while s:
                if self.tabsize != 0:
                    s = string.expandtabs(s,self.tabsize)
                s = string.rstrip(s)
                self.next.append((self.fname,self._lineno,s))
                if len(self.next) > self.READ_BUFFER_MIN:
                    break
                s = self.f.readline()
                if s:
                    self._lineno = self._lineno + 1
        # Return first (oldest) buffer entry.
        if len(self.next) > 0:
            self.cursor = self.next[0]
            del self.next[0]
            result = self.cursor[2]
            # Check for include macro.
            mo = macros.match('+',r'include.?',result)
            if mo and self.include_enabled:
                # Perform glossary substitution on inlcude macro.
                a = subs_glossary([mo.group('target')])
                # If undefined glossary entry then skip to next line of input.
                if not a:
                    return Reader1.read(self)
                fname = a[0]
                if self.include_depth >= self.include_max:
                    raise EAsciiDoc,'maxiumum inlude depth exceeded'
                if not os.path.isabs(fname) and self.fname != '<stdin>':
                    # Include files are relative to parent document directory.
                    fname = os.path.join(os.path.dirname(self.fname),fname)
                if self.fname != '<stdin>' and not os.path.isfile(fname):
                    raise EAsciiDoc,'include file "%s" not found' % (fname,)
                # Parse include macro arguments.
                args = {}
                parse_args(mo.group('caption'),args)
                # Clone self and set as parent (self assumes the role of child).
                parent = Reader1()
                assign(parent,self)
                self.parent = parent
                if args.has_key('tabsize'):
                    self.tabsize = int(validate(args['tabsize'],'int($)>=0', \
                        'illegal include macro tabsize argument'))
                # The include1 variant does not allow nested includes.
                if mo.group('name') == 'include1':
                    self.include_enabled = 0
                self.open(fname)
                self.include_depth = self.include_depth + 1
                result = Reader1.read(self)
        else:
            if not Reader1.eof(self):
                result = Reader1.read(self)
            else:
                result = None
        return result
    def eof(self):
        '''Returns True if all lines have been read.'''
        if len(self.next) == 0:
            # End of current file.
            if self.parent:
                self.closefile()
                assign(self,self.parent)    # Restore parent reader.
                return Reader1.eof(self)
            else:
                return 1
        else:
            return 0
    def read_next(self):
        '''Like read() but does not advance file pointer.'''
        if Reader1.eof(self):
            return None
        else:
            return self.next[0][2]
    def unread(self,cursor):
        '''Push the line (filename,linenumber,linetext) tuple back into the read
        buffer. Note that it's up to the caller to restore the previous
        cursor.'''
        assert cursor
        self.next.insert(0,cursor)

class Reader(Reader1):
    ''' Wraps (well, sought of) Reader1 class and implements conditional text
    inclusion.'''
    def __init__(self):
        Reader1.__init__(self)
        self.depth = 0          # if nesting depth.
        self.skip = 0           # true if we're skipping ifdef...endif.
        self.skipname = ''      # Name of current endif macro target.
        self.skipto = -1        # The depth at which skipping is reenabled.
    def read_super(self):
        result = Reader1.read(self)
        if result is None and self.skip:
            raise EAsciiDoc,'missing endif::%s[]' %(self.skipname,)
        return result
    def read(self):
        result = self.read_super()
        if result is None:
            return None
        while self.skip:
            mo = macros.match('+',r'ifdef|ifndef|endif',result)
            if mo:
                name = mo.group('name')
                target = mo.group('target')
                if name == 'endif':
                    self.depth = self.depth-1
                    if self.depth < 0:
                        raise EAsciiDoc,'"%s" is mismatched' % (result,)
                    if self.depth == self.skipto:
                        self.skip = 0
                        if target and self.skipname != target:
                            raise EAsciiDoc,'"%s" is mismatched' % (result,)
                else:   # ifdef or ifndef.
                    if not target:
                        raise EAsciiDoc,'"%s" missing macro target' % (result,)
                    self.depth = self.depth+1
            result = self.read_super()
            if result is None:
                return None
        mo = macros.match('+',r'ifdef|ifndef|endif',result)
        if mo:
            name = mo.group('name')
            target = mo.group('target')
            if name == 'endif':
                self.depth = self.depth-1
            else:   # ifdef or ifndef.
                if not target:
                    raise EAsciiDoc,'"%s" missing macro target' % (result,)
                defined = document.glossary.get(target) is not None
                if name == 'ifdef':
                    self.skip = not defined
                else:   # ifndef.
                    self.skip = defined
                if self.skip:
                    self.skipto = self.depth
                    self.skipname = target
                self.depth = self.depth+1
            result = self.read()
        return result
    def eof(self):
        return self.read_next() is None
    def read_next(self):
        save_cursor = self.cursor
        result = self.read()
        if result is not None:
            self.unread(self.cursor)
            self.cursor = save_cursor
        return result
    def read_all(self,fname):
        '''Read all lines from file fname and return as list. Use like class
        method: Reader().read_all(fname)'''
        result = []
        self.open(fname)
        try:
            while not self.eof():
                result.append(self.read())
        finally:
            self.close()
        return result
    def read_lines(self,count=1):
        '''Return tuple containing count lines.'''
        result = []
        i = 0
        while i < count and not self.eof():
            result.append(self.read())
        return tuple(result)
    def read_ahead(self,count=1):
        '''Same as read_lines() but does not advance the file pointer.'''
        result = []
        putback = []
        save_cursor = self.cursor
        try:
            i = 0
            while i < count and not self.eof():
                result.append(self.read())
                putback.append(self.cursor)
                i = i+1
            while putback:
                self.unread(putback.pop())
        finally:
            self.cursor = save_cursor
        return tuple(result)
    def skip_blank_lines(self):
        reader.read_until(r'\s*\S+')
    def read_until(self,pattern,same_file=0):
        '''Like read() but reads lines up to (but not including) the first line
        that matches the pattern regular expression. If same_file is True
        then the terminating pattern must occur in the file the was being read
        when the routine was called.'''
        if same_file:
            fname = self.cursor[0]
        result = []
        reo = re.compile(pattern)
        while not self.eof():
            save_cursor = self.cursor
            s = self.read()
            if (not same_file or fname == self.cursor[0]) and reo.match(s):
                self.unread(self.cursor)
                self.cursor = save_cursor
                break
            result.append(s)
        return tuple(result)
    def read_continuation(self):
        '''Like read() but treats trailing backslash as line continuation
        character.'''
        s = self.read()
        if s is None:
            return None
        result = ''
        while s is not None and len(s) > 0 and s[-1] == '\\':
            result = result + s[:-1]
            s = self.read()
        if s is not None:
            result = result + s
        return result
    def parse_arguments(self,dict,default_arg=None):
        '''If an arguments line is in the reader parse it to dict.'''
        s = self.read_next()
        if s is not None:
            if s[:2] == '\\[':
                # Unescape next line.
                save_cursor = self.cursor
                self.read()
                self.cursor = self.cursor[0:2] + (s[1:],)
                self.unread(self.cursor)
                self.cursor = save_cursor
            elif re.match(r'^\[.*[\\\]]$',s):
                s = self.read_continuation()
                if not re.match(r'^\[.*\]$',s):
                    warning('malformed arguments line')
                else:
                    parse_args(s[1:-1],dict,default_arg)

class Writer:
    '''Writes lines to output file.'''
    newline = '\r\n'    # End of line terminator.
    f = None            # Output file object.
    fname= None         # Output file name.
    lines_out = 0       # Number of lines written.
    def open(self,fname):
        self.fname = fname
        verbose('writing: '+fname)
        if fname == '<stdout>':
            self.f = sys.stdout
        else:
            self.f = open(fname,"wb+")
        self.lines_out = 0
    def close(self,):
        if self.fname != '<stdout>':
            self.f.close()
    def write(self,*args):
        '''Iterates arguments, writes tuple and list arguments one line per
        element, else writes argument as single line. If no arguments writes
        blank line. self.newline is appended to each line.'''
        if len(args) == 0:
            self.f.write(self.newline)
            self.lines_out = self.lines_out + 1
        else:
            for arg in args:
                if type(arg) in (TupleType,ListType):
                    for s in arg:
                        self.f.write(s+self.newline)
                    self.lines_out = self.lines_out + len(arg)
                else:
                    self.f.write(arg+self.newline)
                    self.lines_out = self.lines_out + 1
    def write_tag(self,tagname,content,subs=SUBS_DEFAULT):
        '''Write content enveloped by configuration file tag tagname.
        Substitutions specified in the 'subs' list are perform on the
        'content'.'''
        stag,etag = config.tag(tagname)
        self.write(stag,Lex.subs(content,subs),etag)

#---------------------------------------------------------------------------
# Configuration file processing.
#---------------------------------------------------------------------------
def _subs_specialwords(mo):
    '''Special word substitution function called by
    Config.subs_specialwords().'''
    word = mo.re.pattern                # The special word.
    macro = config.specialwords[word]   # The corresponding inline macro.
    if not config.sections.has_key(macro):
        raise EAsciiDoc,'missing special word macro [%s]' % (macro,)
    args = {}
    args['words'] = mo.group()  # The full match string is argument 'words'.
    args.update(mo.groupdict()) # Add named match groups to the arguments.
    # Delete groups that didn't participate in match.
    for k,v in args.items():
        if v is None: del args[k]
    lines = subs_glossary(config.sections[macro],args)
    if len(lines) == 0:
        result = ''
    elif len(lines) == 1:
        result = lines[0]
    else:
        result = string.join(lines,writer.newline)
    return result

class Config:
    '''Methods to process configuration files.'''
    # Predefined section name re's.
    SPECIAL_SECTIONS= ('tags','miscellaneous','glossary','specialcharacters',
            'specialwords','macros','replacements','quotes','titles',
            r'paradef.+',r'listdef.+',r'blockdef.+',r'tabledef.*')
    def __init__(self):
        self.sections = OrderedDict()   # Keyed by section name containing
                                        # lists of section lines.
        # Command-line options.
        self.verbose = 0
        self.suppress_headers = 0       # -s option.
        # [miscellaneous] section.
        self.tabsize = 8
        self.textwidth = 70
        self.newline = '\r\n'
        self.pagewidth = None
        self.pageunits = None
        self.outfilesuffix = ''

        self.tags  = {}         # Values contain (stag,etag) tuples.
        self.specialchars = {}  # Values of special character substitutions.
        self.specialwords = {}  # Name is special word pattern, value is macro.
        self.replacements = {}  # Key is find pattern, value is replace pattern.
        self.specialsections = {} # Name is special section name pattern, value
                                  # is corresponding section name.
        self.quotes = {}        # Values contain corresponding tag name.
        self.fname = ''         # Most recently loaded configuration file name.
        self.conf_gloss = {}    # Glossary entries from conf files.
        self.cmd_gloss = {}     # From command-line -g option glossary entries.
        self.loaded = []        # Loaded conf files.

    def load(self,fname,dir=None):
        '''Loads sections dictionary with section from file fname.
        Existing sections are overlaid. Silently skips missing configuration
        files.'''
        if dir:
            fname = os.path.join(dir, fname)
        # Sliently skip missing configuration file.
        if not os.path.isfile(fname):
            return
        # Don't load conf files twice (local and application conf files are the
        # same if the source file is in the application directory).
        if realpath(fname) in self.loaded:
            return
        rdr = Reader()  # Use instead of file so we can use include:[] macro.
        rdr.open(fname)
        self.fname = fname
        reo = re.compile(r'^\[(?P<section>\w[-\w]*)\]\s*$')
        sections = OrderedDict()
        section,contents = '',[]
        while not rdr.eof():
            s = rdr.read()
            if s and s[0] == '#':       # Skip comment lines.
                continue
            s = string.rstrip(s)
            found = reo.findall(s)
            if found:
                if section:             # Store previous section.
                    if sections.has_key(section) \
                        and self.is_special_section(section):
                        # Merge line oriented special sections.
                        contents = sections[section] + contents
                    sections[section] = contents
                section = string.lower(found[0])
                contents = []
            else:
                contents.append(s)
        if section and contents:        # Store last section.
            if sections.has_key(section) \
                and self.is_special_section(section):
                # Merge line oriented special sections.
                contents = sections[section] + contents
            sections[section] = contents
        rdr.close()
        # Delete blank lines from sections.
        for k in sections.keys():
            for i in range(len(sections[k])-1,-1,-1):
                if not sections[k][i]:
                    del sections[k][i]
                elif not self.is_special_section(k):
                    break   # Only trailing blanks from non-special sections.
        # Merge new sections.
        self.sections.update(sections)
        self.parse_tags()
        # Internally [miscellaneous] section entries are just glossary entries.
        dict = {}
        parse_entries(sections.get('miscellaneous',()),dict,unquote=1)
        update_glossary(self.conf_gloss,dict)
        dict = {}
        parse_entries(sections.get('glossary',()),dict,unquote=1)
        update_glossary(self.conf_gloss,dict)
        # Update document glossary so entries are available immediately.
        document.init_glossary()
        dict = {}
        parse_entries(sections.get('titles',()),dict)
        Title.load(dict)
        parse_entries(sections.get('specialcharacters',()),self.specialchars)
        undefine_entries(self.specialchars)
        parse_entries(sections.get('quotes',()),self.quotes,unique_values=True)
        undefine_entries(self.quotes)
        self.parse_specialwords()
        self.parse_replacements()
        self.parse_specialsections()
        paragraphs.load(sections)
        lists.load(sections)
        blocks.load(sections)
        tables.load(sections)
        macros.load(sections.get('macros',()))
        self.loaded.append(realpath(fname))
            
    def load_all(self,dir):
        '''Load the standard configuration files from directory 'dir'.'''
        self.load('asciidoc.conf',dir)
        conf = document.backend + '.conf'
        self.load(conf,dir)
        conf = document.backend + '-' + document.doctype + '.conf'
        self.load(conf,dir)
        # Load ./filters/*.conf files if they exist.
        filters = os.path.join(dir,'filters')
        if os.path.isdir(filters):
            for file in os.listdir(filters):
                if re.match(r'^.+\.conf$',file):
                    self.load(file,filters)

    def load_miscellaneous(self,dict):
        '''Set miscellaneous configuration entries from dictionary values.'''
        def set_misc(name,rule='1',intval=0):
            if dict.has_key(name):
                errmsg = 'illegal [miscellaneous] %s entry' % name
                if intval:
                    setattr(self, name, int(validate(dict[name],rule,errmsg)))
                else:
                    setattr(self, name, validate(dict[name],rule,errmsg))
        set_misc('tabsize','int($)>0',intval=1)
        set_misc('textwidth','int($)>0',intval=1)
        set_misc('pagewidth','int($)>0',intval=1)
        set_misc('pageunits')
        set_misc('outfilesuffix')
        if dict.has_key('newline'):
            # Convert escape sequences to their character values.
            self.newline = eval('"'+dict['newline']+'"')

    def check(self):
        '''Check the configuration for internal consistancy. Called after all
        configuration files have been loaded.'''
        # Heuristic check that at least one configuration file was loaded.
        if not self.specialchars or not self.tags or not lists:
            raise EAsciiDoc,'incomplete or no configuration files'
        # Check special characters are only one character long.
        for k in self.specialchars.keys():
            if len(k) != 1:
                raise EAsciiDoc,'[specialcharacters] "%s" ' \
                    'must be a single character' % (k,)
        # Check all special words have a corresponding inline macro body.
        for macro in self.specialwords.values():
            if not is_name(macro):
                raise EAsciiDoc,'illegal "%s" special word name' % (macro,)
            if not self.sections.has_key(macro):
                warning('missing special word macro [%s]' % (macro,))
        # Check all text quotes have a corresponding tag.
        for q in self.quotes.keys():
            tag = self.quotes[q]
            if not self.tags.has_key(tag):
                warning('[quotes] %s missing "%s" tag definition'
                    % (q,tag))
        # Check all specialsections section names exist.
        for k,v in self.specialsections.items():
            if not self.sections.has_key(v):
                warning('[%s] missing specialsections section' % (v,))
        paragraphs.check()
        lists.check()
        blocks.check()
        tables.check()
        macros.check()
    
    def is_special_section(self,section_name):
        for name in self.SPECIAL_SECTIONS:
            if re.match(name,section_name):
                return 1
        return 0

    def dump(self):
        '''Dump configuration to stdout.'''
        # Header.
        hdr = ''
        hdr = hdr + '#' + writer.newline
        hdr = hdr + '# Generated by AsciiDoc %s for %s %s.%s' % \
            (VERSION,document.backend,document.doctype,writer.newline)
        t = time.asctime(time.localtime(time.time()))
        hdr = hdr + '# %s%s' % (t,writer.newline)
        hdr = hdr + '#' + writer.newline
        sys.stdout.write(hdr)
        # Dump special sections.
        # Dump only the configuration file and command-line glossary entries.
        # [miscellanous] entries are dumped as part of the [glossary].
        dict = {}
        dict.update(self.conf_gloss)
        dict.update(self.cmd_gloss)
        dump_section('glossary',dict)
        Title.dump()
        dump_section('quotes',self.quotes)
        dump_section('specialcharacters',self.specialchars)
        dict = {}
        for k,v in self.specialwords.items():
            if dict.has_key(v):
                dict[v] = '%s "%s"' % (dict[v],k)   # Append word list.
            else:
                dict[v] = '"%s"' % (k,)
        dump_section('specialwords',dict)
        dump_section('replacements',self.replacements)
        dump_section('specialsections',self.specialsections)
        dict = {}
        for k,v in self.tags.items():
            dict[k] = '%s|%s' % v
        dump_section('tags',dict)
        paragraphs.dump()
        lists.dump()
        blocks.dump()
        tables.dump()
        macros.dump()
        # Dump remaining sections.
        for k in self.sections.keys():
            if not self.is_special_section(k):
                sys.stdout.write('[%s]%s' % (k,writer.newline))
                for line in self.sections[k]:
                    sys.stdout.write('%s%s' % (line,writer.newline))
                sys.stdout.write(writer.newline)

    def subs_section(self,section,dict):
        '''Section glossary substitution from the document.glossary and 'dict'.
        the document.glossary. Lines containing undefinded glossary entries are
        deleted.'''
        if self.sections.has_key(section):
            return subs_glossary(self.sections[section],dict)
        else:
            warning('missing [%s] section' % (section,))
            return ()

    def parse_tags(self):
        '''Parse [tags] section entries into self.tags dictionary.'''
        dict = {}
        parse_entries(self.sections.get('tags',()),dict)
        for k,v in dict.items():
            if not is_name(k):
                raise EAsciiDoc,'[tag] %s malformed' % (k,)
            if v is None:
                if self.tags.has_key(k):
                    del self.tags[k]
            elif v == 'none':
                self.tags[k] = (None,None)
            else:
                mo = re.match(r'(?P<stag>.*)\|(?P<etag>.*)',v)
                if mo:
                    self.tags[k] = (mo.group('stag'), mo.group('etag'))
                else:
                    raise EAsciiDoc,'[tag] %s value malformed' % (k,)

    def tag(self,name):
        '''Returns (starttag,endtag) tuple named name from configuration file
        [tags] section. Raise error if not found'''
        if not self.tags.has_key(name):
            raise EAsciiDoc, 'missing tag "%s"' % (name,)
        return self.tags[name]

    def parse_specialsections(self):
        '''Parse specialsections section to self.specialsections dictionary.'''
        # TODO: This is virtually the same as parse_replacements() and should
        # be factored to single routine.
        dict = {}
        parse_entries(self.sections.get('specialsections',()),dict,1)
        for pat,sectname in dict.items():
            pat = strip_quotes(pat)
            if not is_regexp(pat):
                raise EAsciiDoc,'[specialsections] entry "%s" ' \
                'is not a valid regular expression' % (pat,)
            if sectname is None:
                if self.specialsections.has_key(pat):
                    del self.specialsections[pat]
            else:
                self.specialsections[pat] = sectname

    def parse_replacements(self):
        '''Parse replacements section into self.replacements dictionary.'''
        dict = {}
        #TODO: Deprecated
        if self.sections.has_key('substitutions'):
            parse_entries(self.sections.get('substitutions',()),dict,1)
            warning('[substitutions] deprecated, rename [replacements]')
        else:
            parse_entries(self.sections.get('replacements',()),dict,1)
        for pat,rep in dict.items():
            # The search pattern and the replacement are regular expressions so
            # check them both.
            pat = strip_quotes(pat)
            if not is_regexp(pat):
                raise EAsciiDoc,'"%s" ([replacements] entry in %s) ' \
                'is not a valid regular expression' % (pat,self.fname)
            if rep is None:
                if self.replacements.has_key(pat):
                    del self.replacements[pat]
            else:
                rep = strip_quotes(rep)
                if not is_regexp(pat):
                    raise EAsciiDoc,'[replacements] entry "%s=%s" in %s ' \
                    'is an invalid find regular expression combination'   \
                    % (pat,rep,self.fname)
                self.replacements[pat] = rep

    def subs_replacements(self,s):
        '''Substitute patterns from self.replacements in 's'.'''
        result = s
        for pat,rep in self.replacements.items():
            result = re.sub(pat, rep, result)
        return result

    def parse_specialwords(self):
        '''Parse special words section into self.specialwords dictionary.'''
        reo = re.compile(r'(?:\s|^)(".+?"|[^"\s]+)(?=\s|$)')
        for line in self.sections.get('specialwords',()):
            e = parse_entry(line)
            if not e:
                raise EAsciiDoc,'[specialwords] entry "%s" in %s is malformed' \
                    % (line,self.fname)
            name,wordlist = e
            if not is_name(name):
                raise EAsciiDoc,'[specialwords] name "%s" in %s is illegal' \
                    % (name,self.fname)
            if wordlist == '':
                warning('[specialwords] entry "%s" in %s is blank'
                    % (name,self.fname))
            if wordlist is None:
                # Undefine all words associated with 'name'.
                for k,v in self.specialwords.items():
                    if v == name:
                        del self.specialwords[k]
            else:
                words = reo.findall(wordlist)
                for word in words:
                    word = strip_quotes(word)
                    if not is_regexp(word):
                        raise EAsciiDoc,'"%s" (%s [specialwords] entry in %s)' \
                            'is not a valid regular expression' \
                            % (word,name,self.fname)
                    self.specialwords[word] = name

    def subs_specialchars(self,s):
        '''Perform special character substitution on string 's'.'''
        '''It may seem like a good idea to escape special characters with a '\'
        character, the reason we don't is because the escape character itself
        then has to be escaped and this makes including code listings
        problematic. Use the predefined {amp},{lt},{gt} glossary entries
        instead.'''
        result = ''
        for ch in s:
            result = result + self.specialchars.get(ch,ch)
        return result

    def subs_specialwords(self,s):
        '''Search for word patterns from self.specialwords in 's' and
        substitute using corresponding macro.'''
        result = s
        for word in self.specialwords.keys():
            result = re.sub(word, _subs_specialwords, result)
        return result

    def section2tags(self,section,dict={}):
        '''Perform glossary substitution on 'section' using document glossary
        plus 'dict' glossary. Return tuple (stag,etag) containing pre and post
        | placeholder tags.'''
        if self.sections.has_key(section):
            body = self.sections[section]
        else:
            warning('missing [%s] section' % (section,))
            body = ()
        # Split macro body into start and end tag lists.
        stag = []
        etag = []
        in_stag = 1
        for s in body:
            if in_stag:
                mo = re.match(r'(?P<stag>.*)\|(?P<etag>.*)',s)
                if mo:
                    if mo.group('stag'):
                        stag.append(mo.group('stag'))
                    if mo.group('etag'):
                        etag.append(mo.group('etag'))
                    in_stag = 0
                else:
                    stag.append(s)
            else:
                etag.append(s)
        # Do glossary substitution last so {brkbar} can be used to escape |.
        stag = subs_glossary(stag,dict)
        etag = subs_glossary(etag,dict)
        return (stag,etag)

#---------------------------------------------------------------------------
# Application code.
#---------------------------------------------------------------------------
# Constants
# ---------
APP_DIR = None      # This file's directory.
USER_DIR = None     # ~/.asciidoc

# Globals
# -------
document = Document()       # The document being processed.
config = Config()           # Configuration file reader.
reader = Reader()           # Input stream line reader.
writer = Writer()           # Output stream line writer.
paragraphs = Paragraphs()   # Paragraph definitions.
lists = Lists()             # List definitions.
blocks = DelimitedBlocks()  # DelimitedBlock definitions.
tables = Tables()           # Table definitions.
macros = Macros()           # Macro definitions.

def asciidoc(backend, doctype, confiles, infile, outfile, options):
    '''Convert AsciiDoc document to DocBook document of type doctype
    The AsciiDoc document is read from file object src the translated
    DocBook file written to file object dst.'''
    try:
        if doctype not in ('article','manpage','book'):
            raise EAsciiDoc,'illegal document type'
        if backend == 'linuxdoc' and doctype != 'article':
            raise EAsciiDoc,'%s %s documents are not supported' \
                            % (backend,doctype)
        document.backend = backend
        document.doctype = doctype
        document.init_glossary()
        # Set processing options.
        for o in options:
            if o == '-s': config.suppress_headers = 1
            if o == '-v': config.verbose = 1
        # Check the infile exists.
        if infile != '<stdin>' and not os.path.isfile(infile):
            raise EAsciiDoc,'input file %s missing' % (infile,)
        if '-e' not in options:
            # Load global configuration files from asciidoc directory.
            config.load_all(APP_DIR)
            # Load configuration files from ~/.asciidoc if it exists.
            if USER_DIR is not None:
                config.load_all(USER_DIR)
            # Load configuration files from document directory.
            config.load_all(os.path.dirname(infile))
        if infile != '<stdin>':
            # Load implicit document specific configuration files if they exist.
            config.load(os.path.splitext(infile)[0] + '.conf')
            config.load(os.path.splitext(infile)[0] + '-' + backend + '.conf')
        # If user specified configuration file(s) overlay the defaults.
        if confiles:
            for conf in confiles:
                # First look in current working directory.
                if os.path.isfile(conf):
                    config.load(conf)
                else:
                    raise EAsciiDoc,'configuration file %s missing' % (conf,)
        document.init_glossary()    # Add conf file.
        # Check configuration for consistency.
        config.check()
        # Build outfile name now all conf files have been read.
        if outfile is None:
            outfile = os.path.splitext(infile)[0] + '.' + backend
            if config.outfilesuffix:
                # Change file extension.
                outfile = os.path.splitext(outfile)[0] + config.outfilesuffix
        if '-c' in options:
            config.dump()
        else:
            reader.tabsize = config.tabsize
            reader.open(infile)
            try:
                writer.newline = config.newline
                writer.open(outfile)
                try:
                    document.init_glossary()    # Add file name related entries.
                    document.translate()
                finally:
                    writer.close()
            finally:
                reader.closefile()  # Keep reader state for postmortem.
    except (KeyboardInterrupt, SystemExit):
        print
    except Exception,e:
        # Cleanup.
        if outfile and outfile != '<stdout>' and os.path.isfile(outfile):
            os.unlink(outfile)
        # Build and print error description.
        msg = 'FAILED: '
        if reader.cursor:
            msg = msg + "%s: line %d: " % (reader.cursor[0],reader.cursor[1])
        if isinstance(e,EAsciiDoc):
            print_stderr(msg+str(e))
        else:
            print_stderr(msg+'unexpected error:')
            print_stderr('-'*60)
            traceback.print_exc(file=sys.stderr)
            print_stderr('-'*60)
        sys.exit(1)

def usage(msg=''):
    if msg:
        print_stderr(msg)
    print_stderr('Usage: asciidoc -b backend [-d doctype] [-g glossary-entry]')
    print_stderr('           [-e] [-n] [-s] [-f configfile] [-o outfile]')
    print_stderr('           [--help | -h] [--version] [-v] [ -c ]')
    print_stderr('           infile')

def main():
    # Locate the executable and configuration files directory.
    global APP_DIR,USER_DIR
    APP_DIR = os.path.dirname(realpath(sys.argv[0]))
    USER_DIR = os.environ.get('HOME')
    if USER_DIR is not None:
        USER_DIR = os.path.join(USER_DIR,'.asciidoc')
        if not os.path.isdir(USER_DIR):
            USER_DIR = None
    # Process command line options.
    import getopt
    opts,args = getopt.getopt(sys.argv[1:],
        'b:cd:ef:g:hno:svw:',
        ['help','profile','version'])
    if len(args) > 1:
        usage()
        sys.exit(1)
    backend = None
    doctype = 'article'
    confiles = []
    outfile = None
    options = []
    prof = 0
    for o,v in opts:
        if o in ('--help','-h'):
            print __doc__
            sys.exit(0)
        if o == '--profile':
            prof = 1
        if o == '--version':
            print_stderr('asciidoc version %s' % (VERSION,))
            sys.exit(0)
        if o == '-b': backend = v
        if o == '-c': options.append('-c')
        if o == '-d': doctype = v
        if o == '-e': options.append('-e')
        if o == '-f': confiles.append(v)
        if o == '-n':
            o = '-g'
            v = 'section-numbers'
        if o == '-g':
            e = parse_entry(v)
            if not e:
                usage('Illegal -g %s option' % (v,))
                sys.exit(1)
            k,v = e
            if v is None:
                if k[0] == '^':
                    k = k[1:]
                else:
                    v = ''
            config.cmd_gloss[k] = v
        if o == '-o':
            if v == '-':
                outfile = '<stdout>'
            else:
                outfile = v
        if o == '-n': outfile = v
        if o == '-s': options.append('-s')
        if o == '-v': options.append('-v')
    if len(args) == 0 and len(opts) == 0:
        usage()
        sys.exit(1)
    if len(args) == 0:
        usage('No source file specified')
        sys.exit(1)
    if not backend:
        usage('No backend (-b) option specified')
        sys.exit(1)
    if args[0] == '-':
        infile = '<stdin>'
    else:
        infile = args[0]
    if infile == '<stdin>' and not outfile:
        outfile = '<stdout>'
    # Convert in and out files to absolute paths.
    if infile != '<stdin>': infile = os.path.abspath(infile)
    if outfile and outfile != '<stdout>': outfile = os.path.abspath(outfile)
    # Do the work.
    if prof:
        import profile
        profile.run("asciidoc('%s','%s',(),'%s',None,())"
            % (backend,doctype,infile))
    else:
        asciidoc(backend, doctype, confiles, infile, outfile, options)

if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, SystemExit):
        pass
    except:
        print_stderr("%s: unexpected exit status: %s" %
            (os.path.basename(sys.argv[0]), sys.exc_info()[1]))
    # Exit with previous sys.exit() status or zero if no sys.exit().
    sys.exit(sys.exc_info()[1]) 
