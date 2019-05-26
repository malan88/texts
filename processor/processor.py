import sys
import argparse
import io
import re
import yaml
import json

from string import ascii_lowercase as lowercase

"""Process the pre-formatted and pre-processed (with preprocessor.py) texts into
a json format for the insert scripts to process into the ICC's database.
"""

# Constants
BLANK = re.compile(r'^ *$')
HR = re.compile(r'^\*\*\*$')
QUOTE = re.compile(r'^>')
PRE = re.compile(r'```')
INDENT = re.compile(r'^#+')
INDENT_ENUM = re.compile(r'ind[0-9]*')

ELLIPSE = re.compile(r'[a-zA-Z]+[!,:;&?]?\.{3,5}[!,:;&?]?[a-zA-Z]+')
EMDASH = re.compile(r'[A-Za-z]+[.,;:!?&]?—[.,;:!?&]?[A-Za-z]+')
WORD_BOUNDARY = re.compile(r'\w+|\W')


def readin(fin, matches):
    """Read the file into the script, use the matches dictionary from the yaml
    templating style to process headings and special cases. Returns a list of
    lines of dictionary form:

        {'em': emphasis_status, 'enum': lineclass, 'body': line}

    Where emphasis_status is an enum code for whether a line needs to be
    prefixed or postfixed with an `<em>` or `</em>` tag. These are explained
    below:

    - `nem`: No emphasis, leave these lines alone
    - `oem`: Open emphasis, for lines that have open emphasis that needs to be
      closed by postfixing an `</em>` tag.
    - `em`: Emphasis, for lines that need to be both prefixed with `<em>` and
      postfixed with `</em>`
    - `cem`: Closed emphasis, for lines that need to be prepended with `<em>`
      because they close their own emphasis.

    The purpose of all of this is further explained in the documentation section
    titled "On Emphasis".
    """

    class Switch:
        """A stateful switch-style object for handling all of the possible line
        cases when reading a line into an array with identifying labels.
        """

        lines = []
        pre = False
        # We have to properly output the emphasis status of each line based on
        # the number of underscores. It is highly stateful. It is based on
        # underscores like in markdown, but each line needs a certain data value
        # when we render the html so that we can close and open emphasis tags
        # in cases where the underscore emphasis spans lines. This emswitch
        # method is actually quite elegant. Like a turing machine. The first if
        # statement in the `process_line()` method is where the switch is
        # processed.
        em = 'nem'
        emswitch = {
            'nem': 'oem',
            'oem': 'em',
            'em': 'cem',
            'cem': 'nem',
        }

        def __init__(self, matches):
            """Creates three dictionaries of {<regex>: <lambda>} from:
            - the table of contents headings and levels
            - the special designators (e.g., stage directions)
            - syntax space (e.g., quotes, preformatted lines, etc.
            """
            syntaxspace = {
                BLANK: lambda line: self.lines.append(
                    {'em': self.em,
                     'enum': 'blank',
                     'body': line.strip()}),
                HR: lambda line: self.lines.append(
                    {'em': self.em,
                     'enum': 'hr',
                     'body': '<hr>'}),
                QUOTE: lambda line: self.lines.append(
                    {'em': self.em,
                     'enum': 'quo',
                     'body': line.strip('>').strip()}),
                PRE: lambda line: self.switch_pre(),
                INDENT: lambda line: self.lines.append(
                    {'em': self.em,
                     'enum': f'ind{line.count("#")}',
                     'body': line.strip('#').strip()})
            }

            toc = matches.get('toc', {})
            specials = matches.get('specials', {})

            tocspace = {
                re.compile(key):
                lambda line, key=key, value=value: self.lines.append(
                    {'em': '---',
                     'enum': value["precedence"],
                     'body': line.strip()})
                for (key, value) in toc.items()
            }

            specialsspace = {
                re.compile(key):
                lambda line, value=value: self.lines.append(
                    {'em': self.em,
                     'enum': value['enum'],
                     'body': line.strip()})
                for key, value in specials.items()
            }

            self.searchspace = {**syntaxspace, **tocspace, **specialsspace}

        def switch_pre(self):
            self.pre = not self.pre

        def process_line(self, line):
            # if the # of underscores is odd
            if line.count('_') % 2:
                # Process the emphasis turing machine.
                self.em = self.emswitch[self.em]

            if self.pre:
                # check if the line is a pre tag to flip the switch before we
                # print it out by accident.
                if re.search(PRE, line):
                    self.searchspace[PRE](line)     # flip the switch
                else:
                    self.lines.append({'em': self.em,
                                       'enum': 'pre',
                                       'body': line.strip()})
            else:
                triggered = False
                for regex in self.searchspace:
                    if re.search(regex, line):
                        self.searchspace[regex](line)
                        triggered = True
                        break

                # if the regex searchspace never made a match, it's just text.
                if not triggered:
                    self.lines.append({'em': self.em,
                                       'enum': 'text',
                                       'body': line.strip()})

            if self.em == 'oem' or self.em == 'cem':
                # 'cem' and 'oem' are one time codes.
                self.em = self.emswitch[self.em]

    switcher = Switch(matches)
    for line in fin:
        switcher.process_line(line)

    return switcher.lines


def readout(lines, matches):
    """Read the list of tuples output from readin and return a list of
    context-aware dictionaries with the following key, value pairs for `toc`s
    and `line`s:

    A line of text
    --------------
    `body` : str
        The actual body of the line/toc, stripped of whitespace and unnecessary
        formatting.
    `num`: int
        The numeric attribute for the line, which is the chapter/book number for
        a TOC and the line number for a line.
    `enum` : str
        An enum-type string.

    *line only*
    `emphasis` : int
        A number between 0 and 3 corresponding to the enumerated emphasis codes
        to be translated upon load from the orm (only on lines)

    *toc only*
    `precedence` : int
        The precedence level of the toc (i.e., 1 for the highest precedence, 2
        for lower, etc.)
    """

    class Switch:
        """A stateful switch-style object for context-based line-by-line
        processing using the output of `readout()`.
        """
        # The object's attributes are
        #
        # 1. searchspace: a dictionary of lambdas for processing all the special
        #    cases
        # 2. tocnums: a dictionary for processing the toc hierarchy numbers and
        #    attributes
        # 3. maxtoc: a simple int of the highest level of toc hierarchy
        #    precedence for this book.
        #
        # The obvious ones are defined below.

        lines = []
        num = 0
        prevline = ''
        # enums to search for special space. We're never going to have to worry
        # about more than 6 indents. That would be ridiculous. (Honestly, more
        # than 4 is ridiculous.)
        SPECIALS = ['blank', 'hr', 'quo', 'pre', 'ind1', 'ind2', 'ind3', 'ind4',
                    'ind5', 'ind6']
        SPECIAL = lambda self, line: self.lines.append({**line,
                                                        'num': self.num})
        TEXT = lambda self, line, enum: self.lines.append(
            {'enum': enum,
             'num': self.num,
             'body': line['body'],
             'em': line['em']})

        def __init__(self, matches):
            """Create the necessaries for toc processing."""
            toc = matches.get('toc', {})
            self.tocspace = {value['precedence']:
                             lambda line, value=value: self.lines.append(
                                 {'body': line['body'],
                                  'num': self.tocnums[line['enum']][0],
                                  'precedence': line['enum'],
                                  'enum': value['enum']})
                                 for value in toc.values()}

            # create a dictionary of lists that maps so:
            #       <int:precedence>: [<int:current_num>, <bool:aggregate>]
            self.tocnums = {value['precedence']: [0, value['aggregate']]
                            for value in toc.values()}
            self.maxtoc = max(self.tocnums.keys())

        def update_toc_nums(self, precedence):
            """Update the table of contents numbers. If line['enum'] is not an
            integer, will cause errors. Not to be suppressed.
            """
            self.tocnums[precedence][0] += 1
            # Reset all numbers of lower precedence to 1 if they are not
            # supposed to aggregate.
            for i in range(precedence+1, self.maxtoc+1):
                # if not aggregate
                if not self.tocnums[i][1]:
                    # reset
                    self.tocnums[i][0] = 0

        def process_line(self, line):
            """This method process the actual line, using all of the other
            methods to format the line dictionary, and appends it to the list
            `self.lines`.
            """
            current = line['enum']
            if current == 'blank':
                self.prevline = current
                return
            if isinstance(current, int):
                # if the current enum is an int it is a toc
                self.update_toc_nums(current)
                self.tocspace[current](line)
                self.prevline = current
                return
            self.num += 1
            if current in self.SPECIALS:
                self.SPECIAL(line)
                self.prevline = current
                return
            # test if it is a first line or not
            enum = 'fl' if self.prevline != 'l' else 'l'
            self.TEXT(line, enum)
            self.prevline = enum

    switcher = Switch(matches)
    for line in lines:
        switcher.process_line(line)

    return switcher.lines


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        """Process the preformatted and preprocessed
        (with preprocessor.py) texts into a json format for the insert scripts
        to process into the ICC's database.
        """)
    parser.add_argument('-i', '--input', action='store', type=str,
                        help="The input file. Defaults to stdin.")
    parser.add_argument('-o', '--output', action='store', type=str,
                        help="The output file. Defaults to stdout.")
    parser.add_argument('-m', '--matches', action='store', type=str,
                        required=True, help="The regex matches yaml file "
                        "(required). See the documentation on Processing Texts "
                        "for more information.")
    args = parser.parse_args()

    FIN = io.open(args.input, 'r', encoding='utf-8-sig') if args.input\
        else open(args.input, 'rt', encoding='utf-8-sig')
    FOUT = sys.stdout if not args.output else open(args.output, 'wt')
    MATCHES = yaml.load(open(args.matches, 'rt'), Loader=yaml.FullLoader)

    linesin = readin(FIN, MATCHES)
    linesout = readout(linesin, MATCHES)
    FOUT.write(json.dumps(linesout))
