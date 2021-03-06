#!/usr/bin/python

# This file generated by a program. do not edit.


import pycopia.XML.POM

attribAction_3939340374857665600 = pycopia.XML.POM.XMLAttribute(u'action', pycopia.XML.POM.Enumeration((u'execute-low', u'execute-high', u'cache')), 13, u'execute-low')


attribHref_1415841210624387600 = pycopia.XML.POM.XMLAttribute(u'href', 1, 11, None)




# 
# Service Loading (SL) Document Type Definition.
# 
# Copyright Wireless Application Protocol Forum Ltd., 1998,1999.
#                       All rights reserved.  
# 
# SL is an XML language.  Typical usage:
#    <?xml version="1.0"?>
#    <!DOCTYPE sl PUBLIC "-//WAPFORUM//DTD SL 1.0//EN"
#                 "http://www.wapforum.org/DTD/sl.dtd">
#    <sl>
#    ...
#    </sl>
# 
# Terms and conditions of use are available from the Wireless 
# Application Protocol Forum Ltd. web site at
# http://www.wapforum.org/docs/copyright.htm.
# 


#  URI designating a 
#                                             hypertext node    


# ===================== The SL Element =====================


class Sl(pycopia.XML.POM.ElementNode):
	ATTRIBUTES = {
         u'action': attribAction_3939340374857665600, 
         u'href': attribHref_1415841210624387600, 
         }
	CONTENTMODEL = pycopia.XML.POM.ContentModel(None)
	KWATTRIBUTES = {
         'action': attribAction_3939340374857665600, 
         'href': attribHref_1415841210624387600, 
         }
	_name = u'sl'



_Root = Sl



# 
# Copyright Wireless Application Protocol Forum Ltd., 1998,1999.
#                       All rights reserved.  
# 


GENERAL_ENTITIES = {}

# Cache for dynamic classes for this dtd.


_CLASSCACHE = {}


