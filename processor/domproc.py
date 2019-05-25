from bs4 import BeautifulSoup
import yaml


def descend(tag, parenttags, lines):
    """A recursive function to pull everything within specified parenttags into
    the main namespace (basically flatten the dom into a list of stuff I want).
    """
    if hasattr(tag, 'name') and tag.name in parenttags:
        for t in tag:
            descend(t, parenttags, lines)
    else:
        lines.append(tag)


def reduceandfilter(play, parenttags, filtertags, filters, *args, **kwargs):
    """Reduce and filter a dom into the constituent lines that are necessary.
    This is totally a misnomer (reduce). Oh well.
    """
    play = play.body if hasattr(play, 'body') else play
    lines = []
    for tag in play:
        # eliminate useless parent tags to get everything at the top level.
        # this is what I was calling reduce
        descend(tag, parenttags, lines)
    for filt in filtertags:
        # filter out specified tags
        lines = list(filter(lambda l: l.name != filt, lines))
    for filt in filters:
        # filter elements based on arbitrary lambdas. Especially useful for
        # empty tags.
        lines = list(filter(filt, lines))
    return lines

def format(play, formats):
    """Takes a list of lines and a list of tuples of lambdas, where the first
    lambda is a boolean test and the second one is a formatter.
    """
    lines = []
    for line in play:
        for key, value in formats.items():
            if key(line):
                lines.append(value(line))
                break
    return lines

def get_filters(filters):
    return [eval(filt) for filt in filters]

def get_formatters(dictionary):
    return {eval(key): eval(val) for key, val in dictionary.items()}

def main(args):
    parsers = yaml.load(open(args.parsers, 'rt'))

    filters = (get_filters(parsers['filters'])
               if hasattr(parsers, 'filters') else [])

    lines = reduceandfilter(html, parsers['parenttags'], parsers['filtertags'],
                            filters)

    filters = (get_formatters(parsers['formatters'])
               if hasattr(parsers, 'formatters') else {})

    lines = format(lines, formatters)

if __name__ == '__main__':
    ...
