# -*- coding: utf-8 -*-

# Copyright 2010 Dirk Holtwick, holtwick.it
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from html5lib import treebuilders, inputstream
from xhtml2pdf.default import TAGS, STRING, INT, BOOL, SIZE, COLOR, FILE
from xhtml2pdf.default import BOX, POS, MUST, FONT
from xhtml2pdf.util import getSize, getBool, toList, getColor, getAlign
from xhtml2pdf.util import getBox, getPos, pisaTempFile
from reportlab.platypus.doctemplate import NextPageTemplate, FrameBreak
from reportlab.platypus.flowables import PageBreak, KeepInFrame
from xhtml2pdf.xhtml2pdf_reportlab import PmlRightPageBreak, PmlLeftPageBreak
from xhtml2pdf.tags import * # TODO: Kill wild import!
from xhtml2pdf.tables import * # TODO: Kill wild import!
from xhtml2pdf.util import * # TODO: Kill wild import!
from xml.dom import Node
import copy
import html5lib
import logging
import re
import types
import xhtml2pdf.w3c.cssDOMElementInterface as cssDOMElementInterface
import xml.dom.minidom




log = logging.getLogger("xhtml2pdf")

rxhttpstrip = re.compile("https?://[^/]+(.*)", re.M | re.I)

class AttrContainer(dict):

    def __getattr__(self, name):
        try:
            return dict.__getattr__(self, name)
        except:
            return self[name]

def pisaGetAttributes(c, tag, attributes):
    global TAGS

    attrs = {}
    if attributes:
        for k, v in attributes.items():
            try:
                attrs[str(k)] = str(v) # XXX no Unicode! Reportlab fails with template names
            except:
                attrs[k] = v

    nattrs = {}
    if TAGS.has_key(tag):
        block, adef = TAGS[tag]
        adef["id"] = STRING
        # print block, adef
        for k, v in adef.items():
            nattrs[k] = None
            # print k, v
            # defaults, wenn vorhanden
            if type(v) == types.TupleType:
                if v[1] == MUST:
                    if not attrs.has_key(k):
                        log.warn(c.warning("Attribute '%s' must be set!", k))
                        nattrs[k] = None
                        continue
                nv = attrs.get(k, v[1])
                dfl = v[1]
                v = v[0]
            else:
                nv = attrs.get(k, None)
                dfl = None

            if nv is not None:
                if type(v) == types.ListType:
                    nv = nv.strip().lower()
                    if nv not in v:
                        #~ raise PML_EXCEPTION, "attribute '%s' of wrong value, allowed is one of: %s" % (k, repr(v))
                        log.warn(c.warning("Attribute '%s' of wrong value, allowed is one of: %s", k, repr(v)))
                        nv = dfl

                elif v == BOOL:
                    nv = nv.strip().lower()
                    nv = nv in ("1", "y", "yes", "true", str(k))

                elif v == SIZE:
                    try:
                        nv = getSize(nv)
                    except:
                        log.warn(c.warning("Attribute '%s' expects a size value", k))

                elif v == BOX:
                    nv = getBox(nv, c.pageSize)

                elif v == POS:
                    nv = getPos(nv, c.pageSize)

                elif v == INT:
                    nv = int(nv)

                elif v == COLOR:
                    nv = getColor(nv)

                elif v == FILE:
                    nv = c.getFile(nv)

                elif v == FONT:
                    nv = c.getFontName(nv)

                nattrs[k] = nv

            #for k in attrs.keys():
            #    if not nattrs.has_key(k):
            #        c.warning("attribute '%s' for tag <%s> not supported" % (k, tag))



    #else:
    #    c.warning("tag <%s> is not supported" % tag)

    return AttrContainer(nattrs)

attrNames = '''
    color
    font-family
    font-size
    font-weight
    font-style
    text-decoration
    line-height
    background-color
    display
    margin-left
    margin-right
    margin-top
    margin-bottom
    padding-left
    padding-right
    padding-top
    padding-bottom
    border-top-color
    border-top-style
    border-top-width
    border-bottom-color
    border-bottom-style
    border-bottom-width
    border-left-color
    border-left-style
    border-left-width
    border-right-color
    border-right-style
    border-right-width
    text-align
    vertical-align
    width
    height
    zoom
    page-break-after
    page-break-before
    list-style-type
    list-style-image
    white-space
    text-indent
    -pdf-page-break
    -pdf-frame-break
    -pdf-next-page
    -pdf-keep-with-next
    -pdf-outline
    -pdf-outline-level
    -pdf-outline-open
    -pdf-line-spacing
    -pdf-keep-in-frame-mode
    -pdf-word-wrap
    '''.strip().split()

def getCSSAttr(self, cssCascade, attrName, default=NotImplemented):
    if attrName in self.cssAttrs:
        return self.cssAttrs[attrName]

    try:
        result = cssCascade.findStyleFor(self.cssElement, attrName, default)
    except LookupError:
        result = None

    # XXX Workaround for inline styles
    try:
        style = self.cssStyle
    except:
        style = self.cssStyle = cssCascade.parser.parseInline(self.cssElement.getStyleAttr() or '')[0]
    if style.has_key(attrName):
        result = style[attrName]

    if result == 'inherit':
        if hasattr(self.parentNode, 'getCSSAttr'):
            result = self.parentNode.getCSSAttr(cssCascade, attrName, default)
        elif default is not NotImplemented:
            return default
        else:
            raise LookupError("Could not find inherited CSS attribute value for '%s'" % (attrName,))

    if result is not None:
        self.cssAttrs[attrName] = result
    return result

#TODO: Monkeypatching standard lib should go away.
xml.dom.minidom.Element.getCSSAttr = getCSSAttr

def CSSCollect(node, c):
    #node.cssAttrs = {}
    #return node.cssAttrs
    if c.css:
        node.cssElement = cssDOMElementInterface.CSSDOMElementInterface(node)
        node.cssAttrs = {}
        # node.cssElement.onCSSParserVisit(c.cssCascade.parser)
        cssAttrMap = {}
        for cssAttrName in attrNames:
            try:
                #log.debug("CSSCollect: type=%s, node=%s, attr=%s, value=%s" % (node.__class__, node.tagName, cssAttrName, node.getCSSAttr(c.cssCascade, cssAttrName)))
                cssAttrMap[cssAttrName] = node.getCSSAttr(c.cssCascade, cssAttrName)
            #except LookupError:
            #    pass
            except Exception: # TODO: Kill this catch-all!
                log.debug("CSS error '%s'", cssAttrName, exc_info=1)
    return node.cssAttrs

def CSS2Frag(c, kw, isBlock):

    def safeGetColor(color, default = None):
        try:
            if isinstance(color, list):
                color = tuple(color)
            return getColor(color)
        except ValueError:
            # the css parser is responsible for calculating of inherited values so inherit do not work here
            return getColor(default)

    # COLORS
    if c.cssAttr.has_key("color"):
        c.frag.textColor = safeGetColor(c.cssAttr["color"], default="#000000")
    if c.cssAttr.has_key("background-color"):
        c.frag.backColor = safeGetColor(c.cssAttr["background-color"], default="#ffffff")
    # FONT SIZE, STYLE, WEIGHT
    if c.cssAttr.has_key("font-family"):
        c.frag.fontName = c.getFontName(c.cssAttr["font-family"])
    if c.cssAttr.has_key("font-size"):
        # XXX inherit
        c.frag.fontSize = max(getSize("".join(c.cssAttr["font-size"]), c.frag.fontSize, c.baseFontSize), 1.0)
    if c.cssAttr.has_key("line-height"):
        leading = "".join(c.cssAttr["line-height"])
        c.frag.leading = getSize(leading, c.frag.fontSize)
        c.frag.leadingSource = leading
    else:
        c.frag.leading = getSize(c.frag.leadingSource, c.frag.fontSize)
    if c.cssAttr.has_key("-pdf-line-spacing"):
        c.frag.leadingSpace = getSize("".join(c.cssAttr["-pdf-line-spacing"]))
        # print "line-spacing", c.cssAttr["-pdf-line-spacing"], c.frag.leading
    if c.cssAttr.has_key("font-weight"):
        value = c.cssAttr["font-weight"].lower()
        if value in ("bold", "bolder", "500", "600", "700", "800", "900"):
            c.frag.bold = 1
        else:
            c.frag.bold = 0
    for value in toList(c.cssAttr.get("text-decoration", "")):
        if "underline" in value:
            c.frag.underline = 1
        if "line-through" in value:
            c.frag.strike = 1
        if "none" in value:
            c.frag.underline = 0
            c.frag.strike = 0
    if c.cssAttr.has_key("font-style"):
        value = c.cssAttr["font-style"].lower()
        if value in ("italic", "oblique"):
            c.frag.italic = 1
        else:
            c.frag.italic = 0
    if c.cssAttr.has_key("white-space"):
        # normal | pre | nowrap
        c.frag.whiteSpace = str(c.cssAttr["white-space"]).lower()
    # ALIGN & VALIGN
    if c.cssAttr.has_key("text-align"):
        c.frag.alignment = getAlign(c.cssAttr["text-align"])
    if c.cssAttr.has_key("vertical-align"):
        c.frag.vAlign = c.cssAttr["vertical-align"]
    # HEIGHT & WIDTH
    if c.cssAttr.has_key("height"):
        c.frag.height = "".join(toList(c.cssAttr["height"])) # XXX Relative is not correct!
        if c.frag.height in ("auto",):
            c.frag.height = None
    if c.cssAttr.has_key("width"):
        # print c.cssAttr["width"]
        c.frag.width = "".join(toList(c.cssAttr["width"])) # XXX Relative is not correct!
        if c.frag.width in ("auto",):
            c.frag.width = None
    # ZOOM
    if c.cssAttr.has_key("zoom"):
        # print c.cssAttr["width"]
        zoom = "".join(toList(c.cssAttr["zoom"])) # XXX Relative is not correct!
        if zoom.endswith("%"):
            zoom = float(zoom[: - 1]) / 100.0
        c.frag.zoom = float(zoom)
    # MARGINS & LIST INDENT, STYLE
    if isBlock:
        if c.cssAttr.has_key("margin-top"):
            c.frag.spaceBefore = getSize(c.cssAttr["margin-top"], c.frag.fontSize)
        if c.cssAttr.has_key("margin-bottom"):
            c.frag.spaceAfter = getSize(c.cssAttr["margin-bottom"], c.frag.fontSize)
        if c.cssAttr.has_key("margin-left"):
            c.frag.bulletIndent = kw["margin-left"] # For lists
            kw["margin-left"] += getSize(c.cssAttr["margin-left"], c.frag.fontSize)
            c.frag.leftIndent = kw["margin-left"]
        # print "MARGIN LEFT", kw["margin-left"], c.frag.bulletIndent
        if c.cssAttr.has_key("margin-right"):
            kw["margin-right"] += getSize(c.cssAttr["margin-right"], c.frag.fontSize)
            c.frag.rightIndent = kw["margin-right"]
        # print c.frag.rightIndent
        if c.cssAttr.has_key("text-indent"):
            c.frag.firstLineIndent = getSize(c.cssAttr["text-indent"], c.frag.fontSize)
        if c.cssAttr.has_key("list-style-type"):
            c.frag.listStyleType = str(c.cssAttr["list-style-type"]).lower()
        if c.cssAttr.has_key("list-style-image"):
            c.frag.listStyleImage = c.getFile(c.cssAttr["list-style-image"])
    # PADDINGS
    if isBlock:
        if c.cssAttr.has_key("padding-top"):
            c.frag.paddingTop = getSize(c.cssAttr["padding-top"], c.frag.fontSize)
        if c.cssAttr.has_key("padding-bottom"):
            c.frag.paddingBottom = getSize(c.cssAttr["padding-bottom"], c.frag.fontSize)
        if c.cssAttr.has_key("padding-left"):
            c.frag.paddingLeft = getSize(c.cssAttr["padding-left"], c.frag.fontSize)
        if c.cssAttr.has_key("padding-right"):
            c.frag.paddingRight = getSize(c.cssAttr["padding-right"], c.frag.fontSize)
    # BORDERS
    if isBlock:
        if c.cssAttr.has_key("border-top-width"):
            c.frag.borderTopWidth = getSize(c.cssAttr["border-top-width"], c.frag.fontSize)
        if c.cssAttr.has_key("border-bottom-width"):
            c.frag.borderBottomWidth = getSize(c.cssAttr["border-bottom-width"], c.frag.fontSize)
        if c.cssAttr.has_key("border-left-width"):
            c.frag.borderLeftWidth = getSize(c.cssAttr["border-left-width"], c.frag.fontSize)
        if c.cssAttr.has_key("border-right-width"):
            c.frag.borderRightWidth = getSize(c.cssAttr["border-right-width"], c.frag.fontSize)
        if c.cssAttr.has_key("border-top-style"):
            c.frag.borderTopStyle = c.cssAttr["border-top-style"]
        if c.cssAttr.has_key("border-bottom-style"):
            c.frag.borderBottomStyle = c.cssAttr["border-bottom-style"]
        if c.cssAttr.has_key("border-left-style"):
            c.frag.borderLeftStyle = c.cssAttr["border-left-style"]
        if c.cssAttr.has_key("border-right-style"):
            c.frag.borderRightStyle = c.cssAttr["border-right-style"]
        if c.cssAttr.has_key("border-top-color"):
            c.frag.borderTopColor = safeGetColor(c.cssAttr["border-top-color"], default="#ffffff")
        if c.cssAttr.has_key("border-bottom-color"):
            c.frag.borderBottomColor = safeGetColor(c.cssAttr["border-bottom-color"], default="#ffffff")
        if c.cssAttr.has_key("border-left-color"):
            c.frag.borderLeftColor = safeGetColor(c.cssAttr["border-left-color"], default="#ffffff")
        if c.cssAttr.has_key("border-right-color"):
            c.frag.borderRightColor = safeGetColor(c.cssAttr["border-right-color"], default="#ffffff")

def pisaPreLoop(node, context, collect=False):
    """
    Collect all CSS definitions
    """

    data = u""
    if node.nodeType == Node.TEXT_NODE and collect:
        data = node.data

    elif node.nodeType == Node.ELEMENT_NODE:
        name = node.tagName.lower()

        # print name, node.attributes.items()
        if name in ("style", "link"):
            attr = pisaGetAttributes(context, name, node.attributes)
            # print " ", attr
            media = [x.strip() for x in attr.media.lower().split(",") if x.strip()]
            # print repr(media)

            if (attr.get("type", "").lower() in ("", "text/css") and (
                not media or
                "all" in media or
                "print" in media or
                "pdf" in media)):

                if name == "style":
                    for node in node.childNodes:
                        data += pisaPreLoop(node, context, collect=True)
                    context.addCSS(data)
                    return u""
                    #collect = True

                if name == "link" and attr.href and attr.rel.lower() == "stylesheet":
                    # print "CSS LINK", attr
                    context.addCSS('\n@import "%s" %s;' % (attr.href, ",".join(media)))
                    # context.addCSS(unicode(file(attr.href, "rb").read(), attr.charset))

    #else:
    #    print node.nodeType

    for node in node.childNodes:
        result = pisaPreLoop(node, context, collect=collect)
        if collect:
            data += result

    return data

def pisaLoop(node, context, path=[], **kw):

    # Initialize KW
    if not kw:
        kw = {
            "margin-top": 0,
            "margin-bottom": 0,
            "margin-left": 0,
            "margin-right": 0,
            }
    else:
        kw = copy.copy(kw)

    # indent = len(path) * "  " # only used for debug print statements

    # TEXT
    if node.nodeType == Node.TEXT_NODE:
        # print indent, "#", repr(node.data) #, context.frag
        context.addFrag(node.data)
        # context.text.append(node.value)

    # ELEMENT
    elif node.nodeType == Node.ELEMENT_NODE:
        node.tagName = node.tagName.replace(":", "").lower()

        if node.tagName in ("style", "script"):
            return

        path = copy.copy(path) + [node.tagName]

        # Prepare attributes
        attr = pisaGetAttributes(context, node.tagName, node.attributes)
        #log.debug("pisaLoop: prepare <%s %s>" % (node.tagName, attr) + repr(node.attributes.items())) #, path

        # Calculate styles
        context.cssAttr = CSSCollect(node, context)
        context.node = node

        # Block?
        PAGE_BREAK = 1
        PAGE_BREAK_RIGHT = 2
        PAGE_BREAK_LEFT = 3

        pageBreakAfter = False
        frameBreakAfter = False
        display = context.cssAttr.get("display", "inline").lower()
        # print indent, node.tagName, display, context.cssAttr.get("background-color", None), attr
        isBlock = (display == "block")
        #log.debug("pisaLoop: display: %s" % display);
        if isBlock:
            context.addPara()

            # Page break by CSS
            if context.cssAttr.has_key("-pdf-next-page"):
                context.addStory(NextPageTemplate(str(context.cssAttr["-pdf-next-page"])))
            if context.cssAttr.has_key("-pdf-page-break"):
                if str(context.cssAttr["-pdf-page-break"]).lower() == "before":
                    context.addStory(PageBreak())
            if context.cssAttr.has_key("-pdf-frame-break"):
                if str(context.cssAttr["-pdf-frame-break"]).lower() == "before":
                    context.addStory(FrameBreak())
                if str(context.cssAttr["-pdf-frame-break"]).lower() == "after":
                    frameBreakAfter = True
            if context.cssAttr.has_key("page-break-before"):
                if str(context.cssAttr["page-break-before"]).lower() == "always":
                    context.addStory(PageBreak())
                if str(context.cssAttr["page-break-before"]).lower() == "right":
                    context.addStory(PageBreak())
                    context.addStory(PmlRightPageBreak())
                if str(context.cssAttr["page-break-before"]).lower() == "left":
                    context.addStory(PageBreak())
                    context.addStory(PmlLeftPageBreak())
            if context.cssAttr.has_key("page-break-after"):
                if str(context.cssAttr["page-break-after"]).lower() == "always":
                    pageBreakAfter = PAGE_BREAK
                if str(context.cssAttr["page-break-after"]).lower() == "right":
                    pageBreakAfter = PAGE_BREAK_RIGHT
                if str(context.cssAttr["page-break-after"]).lower() == "left":
                    pageBreakAfter = PAGE_BREAK_LEFT

        if display == "none":
            # print "none!"
            return

        # Translate CSS to frags

        # Save previous frag styles
        context.pushFrag()

        # Map styles to Reportlab fragment properties
        CSS2Frag(context, kw, isBlock)

        # EXTRAS
        if context.cssAttr.has_key("-pdf-keep-with-next"):
            context.frag.keepWithNext = getBool(context.cssAttr["-pdf-keep-with-next"])
        if context.cssAttr.has_key("-pdf-outline"):
            context.frag.outline = getBool(context.cssAttr["-pdf-outline"])
        if context.cssAttr.has_key("-pdf-outline-level"):
            context.frag.outlineLevel = int(context.cssAttr["-pdf-outline-level"])
        if context.cssAttr.has_key("-pdf-outline-open"):
            context.frag.outlineOpen = getBool(context.cssAttr["-pdf-outline-open"])
        if context.cssAttr.has_key("-pdf-word-wrap"):
            context.frag.wordWrap = context.cssAttr["-pdf-word-wrap"]

        # handle keep-in-frame
        keepInFrameMode = None
        keepInFrameMaxWidth = 0
        keepInFrameMaxHeight = 0
        if context.cssAttr.has_key("-pdf-keep-in-frame-mode"):
            value = str(context.cssAttr["-pdf-keep-in-frame-mode"]).strip().lower()
            if value in ("shrink", "error", "overflow", "truncate"):
                keepInFrameMode = value
        if context.cssAttr.has_key("-pdf-keep-in-frame-max-width"):
            keepInFrameMaxWidth = getSize("".join(context.cssAttr["-pdf-keep-in-frame-max-width"]))
        if context.cssAttr.has_key("-pdf-keep-in-frame-max-height"):
            keepInFrameMaxHeight = getSize("".join(context.cssAttr["-pdf-keep-in-frame-max-height"]))

        # ignore nested keep-in-frames, tables have their own KIF handling
        keepInFrame = keepInFrameMode is not None and context.keepInFrameIndex is None
        if keepInFrame:
            # keep track of current story index, so we can wrap everythink
            # added after this point in a KeepInFrame
            context.keepInFrameIndex = len(context.story)

        # BEGIN tag
        klass = globals().get("pisaTag%s" % node.tagName.replace(":", "").upper(), None)
        obj = None
        #log.debug("pisaLoop: begin tag: %s" % node.tagName)

        # Static block
        elementId = attr.get("id", None)
        staticFrame = context.frameStatic.get(elementId, None)
        if staticFrame:
            context.frag.insideStaticFrame += 1
            oldStory = context.swapStory()

        # Tag specific operations
        if klass is not None:
            #log.debug("pisaLoop: klass=%s, attr=%s" % (klass, attr))
            obj = klass(node, attr)
            obj.start(context)

        # Visit child nodes
        context.fragBlock = fragBlock = copy.copy(context.frag)
        for nnode in node.childNodes:
            pisaLoop(nnode, context, path, **kw)
        context.fragBlock = fragBlock

        # END tag
        if obj:
            obj.end(context)
        #log.debug("pisaLoop: end tag: %s" % node.tagName)

        # Block?
        if isBlock:
            context.addPara()

            # XXX Buggy!

            # Page break by CSS
            if pageBreakAfter:
                context.addStory(PageBreak())
                if pageBreakAfter == PAGE_BREAK_RIGHT:
                    context.addStory(PmlRightPageBreak())
                if pageBreakAfter == PAGE_BREAK_LEFT:
                    context.addStory(PmlLeftPageBreak())
            if frameBreakAfter:
                context.addStory(FrameBreak())

        if keepInFrame:
            # get all content added after start of -pdf-keep-in-frame and wrap
            # it in a KeepInFrame
            substory = context.story[context.keepInFrameIndex:]
            context.story = context.story[:context.keepInFrameIndex]
            kwargs = dict(content=substory,
                          maxWidth=keepInFrameMaxWidth,
                          maxHeight=keepInFrameMaxHeight)
            if keepInFrameMode:
                kwargs['mode'] = keepInFrameMode
            context.story.append(KeepInFrame(**kwargs))
            context.keepInFrameIndex = None

        # Static block, END
        if staticFrame:
            context.addPara()
            for frame in staticFrame:
                frame.pisaStaticStory = context.story
            context.swapStory(oldStory)
            context.frag.insideStaticFrame -= 1

        # context.debug(1, indent, "</%s>" % (node.tagName))

        # Reset frag style
        context.pullFrag()

    # Unknown or not handled
    else:
        # context.debug(1, indent, "???", node, node.nodeType, repr(node))
        # Loop over children
        for node in node.childNodes:
            pisaLoop(node, context, path, **kw)

def pisaParser(src, context, default_css="", xhtml=False, encoding=None, xml_output=None):
    """
    - Parse HTML and get miniDOM
    - Extract CSS informations, add default CSS, parse CSS
    - Handle the document DOM itself and build reportlab story
    - Return Context object
    """

    if xhtml:
        #TODO: XHTMLParser doesn't see to exist...
        parser = html5lib.XHTMLParser(tree=treebuilders.getTreeBuilder("dom"))
    else:
        parser = html5lib.HTMLParser(tree=treebuilders.getTreeBuilder("dom"))

    if type(src) in types.StringTypes:
        if type(src) is types.UnicodeType:
            encoding = "utf8"
            src = src.encode(encoding)
        src = pisaTempFile(src, capacity=context.capacity)

    # Test for the restrictions of html5lib
    if encoding:
        # Workaround for html5lib<0.11.1
        if hasattr(inputstream, "isValidEncoding"):
            if encoding.strip().lower() == "utf8":
                encoding = "utf-8"
            if not inputstream.isValidEncoding(encoding):
                log.error("%r is not a valid encoding e.g. 'utf8' is not valid but 'utf-8' is!", encoding)
        else:
            if inputstream.codecName(encoding) is None:
                log.error("%r is not a valid encoding", encoding)
    document = parser.parse(
        src,
        encoding=encoding)

    if xml_output:
        xml_output.write(document.toprettyxml(encoding="utf8"))

    if default_css:
        context.addCSS(default_css)

    pisaPreLoop(document, context)
    #try:
    context.parseCSS()
    #except:
    #    context.cssText = DEFAULT_CSS
    #    context.parseCSS()
    # context.debug(9, pprint.pformat(context.css))
    pisaLoop(document, context)
    return context

# Shortcuts

HTML2PDF = pisaParser

def XHTML2PDF(*a, **kw):
    kw["xhtml"] = True
    return HTML2PDF(*a, **kw)

XML2PDF = XHTML2PDF
