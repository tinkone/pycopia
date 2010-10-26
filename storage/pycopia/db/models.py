#!/usr/bin/python2.6
# -*- coding: us-ascii -*-
# vim:ts=4:sw=4:softtabstop=0:smarttab
#
#    Copyright (C) 2009  Keith Dart <keith@kdart.com>
#
#    This library is free software; you can redistribute it and/or
#    modify it under the terms of the GNU Lesser General Public
#    License as published by the Free Software Foundation; either
#    version 2.1 of the License, or (at your option) any later version.
#
#    This library is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
#    Lesser General Public License for more details.

"""
Defines database ORM objects.

"""

import logging
import collections
from datetime import timedelta
from hashlib import sha1

from sqlalchemy import create_engine, and_, or_, not_, func, exists
from sqlalchemy.orm import (sessionmaker, mapper, relation, class_mapper,
        backref, synonym, _mapper_registry, validates)
from sqlalchemy.orm.properties import ColumnProperty, RelationshipProperty
from sqlalchemy.orm.collections import column_mapped_collection
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.ext.associationproxy import association_proxy

from pycopia.aid import hexdigest, unhexdigest, Enums, removedups, NULL

from pycopia.db import tables
from pycopia.db.types import validate_value_type, OBJ_TESTRUNNER


class ModelError(Exception):
    pass


def create_session(url=None):
    if url is None:
        from pycopia import basicconfig
        cf = basicconfig.get_config("storage.conf")
        url = cf["database"]
    db = create_engine(url)
    tables.metadata.bind = db
    return sessionmaker(bind=db, autoflush=False)


# Get a database session instance from a database url. If URL is not
# provided then get it from the storage.conf configuration file.
def get_session(url=None):
    session_class = create_session(url)
    return session_class()


# Due to the way sqlalchemy instruments attributes you cannot instantiate
# new model objects in the usual way. Use this general factory function instead.
def create(klass, **kwargs):
    inst = klass()
    for k, v in kwargs.iteritems():
        setattr(inst, k, v)
    return inst

def update(inst, **kwargs):
    for k, v in kwargs.iteritems():
        setattr(inst, k, v)

# Set password encryption key for the site.
SECRET_KEY = None
def _get_secret():
    global SECRET_KEY
    from pycopia import basicconfig
    try:
        cf = basicconfig.get_config("auth.conf")
        SECRET_KEY = cf.SECRET_KEY
    except basicconfig.ConfigReadError:
        logging.warn("User encryption key not found for auth app, using default.")
        SECRET_KEY = "Testkey"



#######################################
# User management for AAA for web applications.

class Permission(object):
    ROW_DISPLAY = ("name", "description")

    def __str__(self):
        return str(self.name)

    def __repr__(self):
        return "Permission(%r, %r)" % (self.name, self.description)

mapper(Permission, tables.auth_permission)


class Group(object):
    ROW_DISPLAY = ("name", "permissions")

    def __str__(self):
        return str(self.name)

    def __repr__(self):
        return "Group(%r)" % (self.name,)

mapper(Group, tables.auth_group,
    properties={
        "permissions": relation(Permission, lazy=True, secondary=tables.auth_group_permissions),
    }
)


class User(object):
    ROW_DISPLAY = ("username", "first_name", "last_name", "email")

    def __str__(self):
        return "%s %s (%s)" % (self.first_name, self.last_name, self.username)

    def __repr__(self):
        return "User(%r, %r, %r)" % (self.username, self.first_name, self.last_name)

    # Passwords are stored in the database encrypted.
    def _set_password(self, passwd):
        # pycrypto package.  http://www.amk.ca/python/code/crypto
        from Crypto.Cipher import AES
        eng = AES.new(get_key(), AES.MODE_ECB)
        self._password = hexdigest(eng.encrypt((passwd + "\0"*(16 - len(passwd)))[:16]))

    def _get_password(self):
        from Crypto.Cipher import AES
        eng = AES.new(get_key(), AES.MODE_ECB)
        return eng.decrypt(unhexdigest(self._password)).strip("\0")

    password = property(_get_password, _set_password)

    def set_last_login(self):
            self.last_login = tables.time_now()

    def get_session_key(self):
        h = sha1()
        h.update(str(self.id))
        h.update(self.username)
        h.update(str(self.last_login))
        return h.hexdigest()

    @classmethod
    def get_by_username(cls, dbsession, username):
        return dbsession.query(cls).filter(cls.username==username).one()


def get_key():
    global SECRET_KEY, _get_secret
    if SECRET_KEY is None:
        _get_secret()
        del _get_secret
    h = sha1()
    h.update(SECRET_KEY)
    h.update("ifucnrdthsurtoocls")
    return h.digest()[:16]


mapper(User, tables.auth_user,
    properties={
        "permissions": relation(Permission, lazy=True, secondary=tables.auth_user_user_permissions),
        "groups": relation(Group, lazy=True, secondary=tables.auth_user_groups),
        "password": synonym('_password', map_column=True),
#        "full_name": column_property( (tables.auth_user.c.first_name + " " +
#                tables.auth_user.c.last_name).label('full_name') ),
    })



def create_user(session, pwent):
    """Create a new user with a default password and name taken from the
    password entry (from the passwd module). 
    """
    now = tables.time_now()
    fullname = pwent.gecos
    if fullname:
        if "," in fullname:
            [last, first] = fullname.split(",", 1)
        else:
            fnparts = fullname.split(None, 1)
            if len(fnparts) == 2:
                [first, last] = fnparts
            else:
                first, last = pwent.name, fnparts[0]
    else: # some places have empty gecos
        if "." in pwent.name:
            [first, last] = map(str.capitalize, pwent.name.split(".", 1))
        else:
            first, last = pwent.name, "" # Punt, first name is login name.  User can edit later.
    grp = session.query(Group).filter(Group.name=="testing").one() # should already exist
    user = create(User, username=pwent.name, first_name=first, last_name=last, authservice="system",
            is_staff=True, is_active=True, is_superuser=False, last_login=now, date_joined=now)
    user.password = pwent.name + "123" # default, temporary password
    user.groups = [grp]
    session.add(user)
    session.commit()
    return user


class UserMessage(object):
    ROW_DISPLAY = ("user", "message")

    def __unicode__(self):
        return unicode(self.message)

    def __str__(self):
        return "%s: %s" % (self.user, self.message)

mapper(UserMessage, tables.auth_message,
    properties={
        "user": relation(User, backref=backref("messages",
                    cascade="all, delete, delete-orphan")),
    }
)


# end USERS
#######################################

class Cookie(object):
    pass
mapper(Cookie, tables.cookies)

#######################################
# SESSIONS for web server sessions

class Session(object):
    def __init__(self, user, lifetime=48):
        self.session_key = user.get_session_key()
        self.expire_date = user.last_login + timedelta(hours=lifetime)
        self.data = { "username": user.username }

    def __getitem__(self, key):
        return self.data[key]

    def __setitem__(self, key, value):
        d = self.data
        d[key] = value
        self.data = d

    def __delitem__(self, key):
        d = self.data
        del d[key]
        self.data = d

    def __str__(self):
        return "key: %s: Expires: %s" % (self.session_key, self.expire_date)

    def is_expired(self):
        return tables.time_now() >= self.expire_date

    @classmethod
    def get_expired(cls, session):
        return session.query(cls).filter(cls.expire_date < "now").order_by(cls.expire_date).all()

    @classmethod
    def clean(cls, session):
        for sess in session.query(cls).filter(cls.expire_date < "now").all():
            session.delete(sess)
        session.commit()




mapper(Session, tables.client_session)

# end SESSIONS
#######################################


class Country(object):
    ROW_DISPLAY = ("name", "isocode")

    def __str__(self):
        return "%s(%s)" % (self.name, self.isocode)

    def __repr__(self):
        return "Country(%r, %r)" % (self.name, self.isocode)


mapper(Country, tables.country_codes)


class CountrySet(object):
    ROW_DISPLAY = ("name",)

    def __repr__(self):
        return self.name


mapper(CountrySet, tables.country_sets,
    properties={
        "countries": relation(Country, lazy=True, secondary=tables.country_sets_countries),
    }
)


#######################################
# Misc

class LoginAccount(object):
    ROW_DISPLAY = ("identifier", "login")

    def __str__(self):
        return str(self.identifier)

mapper(LoginAccount, tables.account_ids)


class Language(object):
    ROW_DISPLAY = ("name", "isocode")

    def __str__(self):
        return "%s(%s)" % (self.name, self.isocode)

    def __repr__(self):
        return "Language(%r, %r)" % (self.name, self.isocode)

mapper(Language, tables.language_codes)


class LanguageSet(object):
    ROW_DISPLAY = ("name", )

    def __str__(self):
        return str(self.name)

mapper(LanguageSet, tables.language_sets, 
    properties={
        "languages": relation(Language, lazy=True, secondary=tables.language_sets_languages),
    }
)


class Address(object):
    ROW_DISPLAY = ("address", "address2", "city", "stateprov", "postalcode")

    def __str__(self):
        return "%s, %s, %s %s" % (self.address, self.city, self.stateprov, self.postalcode)

    def __repr__(self):
        return "Address(%r, %r, %r, %r, %r)" % (
                self.address, self.address2, self.city, self.stateprov, self.postalcode)

mapper(Address, tables.addresses,
    properties={
        "country": relation(Country),
    }
)


class Contact(object):
    ROW_DISPLAY = ("lastname", "firstname", "middlename", "email")

    def __str__(self):
        if self.email:
            return "%s %s <%s>" % (self.firstname, self.lastname, self.email)
        else:
            return "%s %s" % (self.firstname, self.lastname)

mapper(Contact, tables.contacts,
    properties={
        "address": relation(Address),
        "user": relation(User),
    }
)


class Schedule(object):
    ROW_DISPLAY = ("name", "user", "minute", "hour", "day_of_month", "month", "day_of_week")

    def __str__(self):
        return "%s: %s %s %s %s %s" % (self.name, self.minute, self.hour,
                self.day_of_month, self.month, self.day_of_week)

    def __repr__(self):
        return "Schedule(%r, %r, %r, %r, %r, %r)" % (self.name, self.minute, self.hour,
                self.day_of_month, self.month, self.day_of_week)

mapper(Schedule, tables.schedule,
    properties={
        "user": relation(User),
    }
)


class Location(object):
    ROW_DISPLAY = ("locationcode",)

    def __str__(self):
        return str(self.locationcode)

mapper(Location, tables.location,
    properties={
        "address": relation(Address),
        "contact": relation(Contact),
    }
)

### general attributes

class AttributeType(object):
    ROW_DISPLAY = ("name", "value_type", "description")

    def __str__(self):
        return "%s(%s)" % (self.name, self.value_type)

    @classmethod
    def get_by_name(cls, session, name):
        try:
            attrtype = session.query(cls).filter(cls.name==str(name)).one()
        except NoResultFound:
            raise ModelError("No attribute type %r defined." % (name,))
        return attrtype

    @classmethod
    def get_attribute_list(cls, session):
        return session.query(cls.name, cls.value_type).all()

mapper(AttributeType, tables.attribute_type)



#######################################
# projects

class ProjectCategory(object):
    ROW_DISPLAY = ("name",)

    def __repr__(self):
        return self.name

mapper(ProjectCategory, tables.project_category)


class FunctionalArea(object):
    ROW_DISPLAY = ("name",)

    def __str__(self):
        return str(self.name)

    def __repr__(self):
        return "FunctionalArea(%r)" % self.name


mapper(FunctionalArea, tables.functional_area)


class Component(object):
    ROW_DISPLAY = ("name", "description", "created")

    def __repr__(self):
        return self.name

mapper(Component, tables.components)


class Project(object):
    ROW_DISPLAY = ("name", "category", "description")

    def __str__(self):
        return str(self.name)

mapper(Project, tables.projects,
    properties={
        "components": relation(Component, lazy=True, secondary=tables.projects_components),
        "category": relation(ProjectCategory, backref="projects"),
        "leader": relation(Contact),
    }
)

class ProjectVersion(object):
    ROW_DISPLAY = ("project", "major", "minor", "subminor", "build")

    def __str__(self):
        return "%s %s.%s.%s-%s" % (self.project, self.major, self.minor,
                self.subminor, self.build)

mapper(ProjectVersion, tables.project_versions, 
    properties={
        "project": relation(Project),
    }
)


#######################################
# Corporations

class CorporateAttributeType(object):
    ROW_DISPLAY = ("name", "value_type", "description")

    @classmethod
    def get_by_name(cls, session, name):
        try:
            attrtype = session.query(cls).filter(cls.name==str(name)).one()
        except NoResultFound:
            raise ModelError("No attribute type %r defined." % (name,))
        return attrtype

    @classmethod
    def get_attribute_list(cls, session):
        return session.query(cls.name, cls.value_type).all()

    def __str__(self):
        return "%s(%s)" % (self.name, self.value_type)

mapper(CorporateAttributeType, tables.corp_attribute_type)



class Corporation(object):
    ROW_DISPLAY = ("name",)

    def __str__(self):
        return str(self.name)

    def set_attribute(self, session, attrname, value):
        attrtype = CorporateAttributeType.get_by_name(session, str(attrname))
        existing = session.query(CorporateAttribute).filter(and_(CorporateAttribute.corporation==self, 
                            CorporateAttribute.type==attrtype)).scalar()
        if existing is not None:
            existing.value = value
        else:
            attrib = create(CorporateAttribute, corporation=self, type=attrtype, value=value)
            session.add(attrib)
            self.attributes.append(attrib)
        session.commit()

    def get_attribute(self, session, attrname):
        attrtype = CorporateAttributeType.get_by_name(session, str(attrname))
        try:
            ea = session.query(CorporateAttribute).filter(and_(CorporateAttribute.corporation==self, 
                            CorporateAttribute.type==attrtype)).one()
        except NoResultFound:
            raise ModelError("No attribute %r set." % (attrname,))
        return ea.value

    def del_attribute(self, session, attrtype):
        attrtype = CorporateAttributeType.get_by_name(session, str(attrtype))
        attrib = session.query(CorporateAttribute).filter(and_(
                CorporateAttribute.corporation==self, CorporateAttribute.type==attrtype)).scalar()
        if attrib:
            self.attributes.remove(attrib)
        session.commit()

    @staticmethod
    def get_attribute_list(session):
        return CorporateAttributeType.get_attribute_list(session)

    def add_service(self, session, service):
        svc = session.query(FunctionalArea).filter(FunctionArea.name == service).one()
        self.services.append(svc)

    def del_service(self, session, service):
        svc = session.query(FunctionalArea).filter(FunctionArea.name == service).one()
        self.services.remove(svc)


mapper(Corporation, tables.corporations,
    properties={
        "services": relation(FunctionalArea, lazy=True, secondary=tables.corporations_services),
        "address": relation(Address),
        "contact": relation(Contact),
        "country": relation(Country),
#        "parent": relation(Corporation,  backref="subsidiaries"),
#        "parent": relation(Corporation,  backref=backref("subsidiaries",
#                                remote_side=[tables.corporations.c.id])),
    }
)


class CorporateAttribute(object):
    ROW_DISPLAY = ("type", "value")

    def __repr__(self):
        return "%s=%s" % (self.type, self.value)

    @validates("value")
    def validate_value(self, attrname, value):
        return validate_value_type(self.type.value_type, value)


mapper(CorporateAttribute, tables.corp_attributes,
    properties={
        "type": relation(CorporateAttributeType),
        "corporation": relation(Corporation, backref=backref("attributes", 
                    cascade="all, delete, delete-orphan")),
    }
)


#######################################
# Software model

# This SoftwareCategory also specifies the role, function, or service.
# It's used for Software to categorize the type or role of it, and for
# Equipment functions that run that sofware to provide that role or
# service.

class SoftwareCategory(object):
    ROW_DISPLAY = ("name", "description")

    def __repr__(self):
        return str(self.name)

mapper(SoftwareCategory, tables.software_category)


# A localized version of a software that indicates the current
# configuration of encoding and language.
class SoftwareVariant(object):
    ROW_DISPLAY = ("name", "encoding")

    def __repr__(self):
        return "%s(%s)" % (self.name, self.encoding)

mapper(SoftwareVariant, tables.software_variant,
    properties={
        "language": relation(Language),
        "country": relation(Country),
    }
)


class Software(object):
    ROW_DISPLAY = ("name", "category", "manufacturer", "vendor")

    def __repr__(self):
        return self.name

    def set_attribute(self, session, attrname, value):
        attrtype = AttributeType.get_by_name(session, str(attrname))
        existing = session.query(SoftwareAttribute).filter(and_(SoftwareAttribute.software==self, 
                            SoftwareAttribute.type==attrtype)).scalar()
        if existing is not None:
            existing.value = value
        else:
            attrib = create(SoftwareAttribute, software=self, type=attrtype, value=value)
            session.add(attrib)
            self.attributes.append(attrib)
        session.commit()

    def get_attribute(self, session, attrname):
        attrtype = AttributeType.get_by_name(session, str(attrname))
        try:
            ea = session.query(SoftwareAttribute).filter(and_(SoftwareAttribute.software==self, 
                            SoftwareAttribute.type==attrtype)).one()
        except NoResultFound:
            raise ModelError("No attribute %r set." % (attrname,))
        return ea.value

    def del_attribute(self, session, attrtype):
        attrtype = AttributeType.get_by_name(session, str(attrtype))
        attrib = session.query(SoftwareAttribute).filter(and_(
                SoftwareAttribute.software==self, SoftwareAttribute.type==attrtype)).scalar()
        if attrib:
            self.attributes.remove(attrib)
        session.commit()

    @staticmethod
    def get_attribute_list(session):
        return AttributeType.get_attribute_list(session)


mapper (Software, tables.software,
    properties={
        "variants": relation(SoftwareVariant, lazy=True, secondary=tables.software_variants),
        "category": relation(SoftwareCategory),
        "vendor": relation(Corporation, 
                primaryjoin=tables.software.c.vendor_id==tables.corporations.c.id),
        "manufacturer": relation(Corporation, 
                primaryjoin=tables.software.c.manufacturer_id==tables.corporations.c.id),
    }
)

class SoftwareAttribute(object):
    ROW_DISPLAY = ("type", "value")

    def __repr__(self):
        return "%s=%s" % (self.type, self.value)

    @validates("value")
    def validate_value(self, attrname, value):
        return validate_value_type(self.type.value_type, value)

mapper(SoftwareAttribute, tables.software_attributes,
    properties={
            "software": relation(Software, backref=backref("attributes", 
                    cascade="all, delete, delete-orphan")),
            "type": relation(AttributeType),
    },
)



#######################################
# Equipment model

# similar to ENTITY-MIB::PhysicalClass
class EquipmentCategory(object):

    def __str__(self):
        return "%s(%d)" % (self.name, self.id + 1)

mapper(EquipmentCategory, tables.equipment_category)

# IANAifType, minus obsolete and deprecated.
class InterfaceType(object):

    def __str__(self):
        return "%s(%d)" % (self.name, self.enumeration)

mapper(InterfaceType, tables.interface_type)


class Network(object):
    ROW_DISPLAY = ("name", "layer", "vlanid", "ipnetwork", "notes")

    def __str__(self):
        if self.layer == 2 and self.vlanid is not None:
            return "%s {%s}" % (self.name, self.vlanid)
        elif self.layer == 3 and self.ipnetwork is not None:
            return "%s (%s)" % (self.name, self.ipnetwork)
        else:
            return "%s[%d]" % (self.name, self.layer)

    def __repr__(self):
        return "Network(%r, %r, %r, %r)" % (self.name, self.layer, self.vlanid, self.ipnetwork)

mapper(Network, tables.networks,
    properties={
        "upperlayers": relation(Network, backref=backref("lowerlayer",
                remote_side=[tables.networks.c.id])),
    },
)


class EquipmentModel(object):
    ROW_DISPLAY = ("manufacturer", "name", "category")

    def __str__(self):
        return str(self.name)

    def set_attribute(self, session, attrname, value):
        attrtype = AttributeType.get_by_name(session, str(attrname))
        existing = session.query(EquipmentModelAttribute).filter(and_(EquipmentModelAttribute.equipmentmodel==self, 
                            EquipmentModelAttribute.type==attrtype)).scalar()
        if existing is not None:
            existing.value = value
        else:
            attrib = create(EquipmentModelAttribute, equipmentmodel=self, type=attrtype, value=value)
            session.add(attrib)
            self.attributes.append(attrib)
        session.commit()

    def get_attribute(self, session, attrname):
        attrtype = AttributeType.get_by_name(session, str(attrname))
        try:
            ea = session.query(EquipmentModelAttribute).filter(and_(EquipmentModelAttribute.equipmentmodel==self, 
                            EquipmentModelAttribute.type==attrtype)).one()
        except NoResultFound:
            raise ModelError("No attribute %r set." % (attrname,))
        return ea.value

    def del_attribute(self, session, attrtype):
        attrtype = AttributeType.get_by_name(session, str(attrtype))
        attrib = session.query(EquipmentModelAttribute).filter(and_(
                EquipmentModelAttribute.equipmentmodel==self, EquipmentModelAttribute.type==attrtype)).scalar()
        if attrib:
            self.attributes.remove(attrib)
        session.commit()

    @staticmethod
    def get_attribute_list(session):
        return AttributeType.get_attribute_list(session)


mapper(EquipmentModel, tables.equipment_model,
    properties={
        "embeddedsoftware": relation(Software, secondary=tables.equipment_model_embeddedsoftware),
        "category": relation(EquipmentCategory, order_by=tables.equipment_category.c.name),
        "manufacturer": relation(Corporation, order_by=tables.corporations.c.name),
    }
)


class EquipmentModelAttribute(object):
    ROW_DISPLAY = ("type", "value")

    def __repr__(self):
        return "%s=%s" % (self.type, self.value)

    @validates("value")
    def validate_value(self, attrname, value):
        return validate_value_type(self.type.value_type, value)

mapper(EquipmentModelAttribute, tables.equipment_model_attributes,
    properties={
            "equipmentmodel": relation(EquipmentModel, backref=backref("attributes", 
                    cascade="all, delete, delete-orphan")),
            "type": relation(AttributeType),
    },
)


class Equipment(object):
    ROW_DISPLAY = ("name", "model", "serno")

    def __str__(self):
        return str(self.name)

    def set_attribute(self, session, attrname, value):
        attrtype = AttributeType.get_by_name(session, str(attrname))
        existing = session.query(EquipmentAttribute).filter(and_(EquipmentAttribute.equipment==self, 
                            EquipmentAttribute.type==attrtype)).scalar()
        if existing is not None:
            existing.value = value
        else:
            attrib = create(EquipmentAttribute, equipment=self, type=attrtype, value=value)
            session.add(attrib)
            self.attributes.append(attrib)
        session.commit()

    def get_attribute(self, session, attrname):
        attrtype = AttributeType.get_by_name(session, str(attrname))
        try:
            ea = session.query(EquipmentAttribute).filter(and_(EquipmentAttribute.equipment==self, 
                            EquipmentAttribute.type==attrtype)).one()
        except NoResultFound:
            raise ModelError("No attribute %r set." % (attrname,))
        return ea.value

    def del_attribute(self, session, attrname):
        attrtype = AttributeType.get_by_name(session, str(attrname))
        attrib = session.query(EquipmentAttribute).filter(and_(
                EquipmentAttribute.equipment==self, EquipmentAttribute.type==attrtype)).scalar()
        if attrib:
            self.attributes.remove(attrib)
        session.commit()

    @staticmethod
    def get_attribute_list(session):
        return AttributeType.get_attribute_list(session)

    # interface management
    def add_interface(self, session, name, 
                ifindex=None, interface_type=None, macaddr=None, ipaddr=None, network=None):
        if interface_type is not None and isinstance(interface_type, basestring):
            interface_type = session.query(InterfaceType).filter(InterfaceType.name==interface_type).one()
        if network is not None and isinstance(network, basestring):
            network = session.query(Network).filter(Network.name==network).one()
        intf = create(Interface, name=name, equipment=self, ifindex=ifindex,
                interface_type=interface_type, macaddr=macaddr, ipaddr=ipaddr,
                network=network)
        session.add(intf)
        self.interfaces[name] = intf
        session.commit()

    def del_interface(self, session, name):
        del self.interfaces[name]
        session.commit()

    @property
    def any_interface(self):
        keys = self.interfaces.keys()
        if keys:
            return self.interfaces[keys[0]]
        else:
            return None

    def connect(self, session, intf, network, force=False):
        """Connect this equipments named interface to a network.

        If "force" is True then alter network part of address to match
        network.
        """
        intf = self.interfaces[intf]
        if isinstance(network, basestring):
            network = session.query(Network).filter(Network.name==network).one()
        # alter the IP mask to match the network
        addr = intf.ipaddr
        if addr is not None and network.ipnetwork is not None:
            addr.maskbits = network.ipnetwork.maskbits
            if addr.network != network.ipnetwork.network:
                if force:
                    addr.network = network.ipnetwork.network
                else:
                    raise ModelError("Can't add interface to network with different network numbers.")
            intf.ipaddr = addr
        intf.network = network
        session.commit()

    def disconnect(self, session, intf):
        intf = self.interfaces[intf]
        intf.network = None
        session.commit()

    # properties provided elsewhere:
    #    attributes
    #    capabilities

mapper(Equipment, tables.equipment,
    properties={
        "model": relation(EquipmentModel),
        "owner": relation(User),
        "vendor": relation(Corporation),
        "account": relation(LoginAccount),
        "language": relation(Language),
        "location": relation(Location),
        "subcomponents": relation(Equipment, 
                backref=backref('parent', remote_side=[tables.equipment.c.id])),
        "software": relation(Software, lazy=True, secondary=tables.equipment_software),
    },
)


class EquipmentAttribute(object):
    ROW_DISPLAY = ("type", "value")

    def __repr__(self):
        return "%s=%s" % (self.type, self.value)

    @validates("value")
    def validate_value(self, attrname, value):
        return validate_value_type(self.type.value_type, value)

mapper(EquipmentAttribute, tables.equipment_attributes,
    properties={
            "equipment": relation(Equipment, backref=backref("attributes", 
                    cascade="all, delete, delete-orphan")),
            "type": relation(AttributeType),
    },
)


class Interface(object):
    ROW_DISPLAY = ("name", "ifindex", "interface_type", "equipment", "macaddr", "ipaddr", "network")

    def __str__(self):
        return "%s (%s)" % (self.name, self.ipaddr)

    def __repr__(self):
        return "Interface(%r, ipaddr=%r)" % (self.name, self.ipaddr)

mapper(Interface, tables.interfaces,
    properties = {
        "interface_type": relation(InterfaceType, order_by=tables.interface_type.c.name),
        "parent": relation(Interface, backref=backref("subinterface",
                                remote_side=[tables.interfaces.c.id])),
        "network": relation(Network, backref="interfaces", order_by=tables.networks.c.name),
        "equipment": relation(Equipment, 
                backref=backref("interfaces", collection_class=column_mapped_collection(tables.interfaces.c.name))),
    }
)


### environments

class EnvironmentAttributeType(object):
    ROW_DISPLAY = ("name", "value_type", "description")

    def __str__(self):
        return "%s(%s)" % (self.name, self.value_type)

    @classmethod
    def get_by_name(cls, session, name):
        try:
            attrtype = session.query(cls).filter(cls.name==str(name)).one()
        except NoResultFound:
            raise ModelError("No attribute type %r defined." % (name,))
        return attrtype

    @classmethod
    def get_attribute_list(cls, session):
        return session.query(cls.name, cls.value_type).all()


mapper(EnvironmentAttributeType, tables.environmentattribute_type,
)


class Environment(object):
    ROW_DISPLAY = ("name", "owner")

    def __repr__(self):
        return self.name

    def set_attribute(self, session, attrname, value):
        attrtype = EnvironmentAttributeType.get_by_name(session, str(attrname))
        existing = session.query(EnvironmentAttribute).filter(and_(EnvironmentAttribute.environment==self, 
                            EnvironmentAttribute.type==attrtype)).scalar()
        if existing is not None:
            existing.value = value
        else:
            attrib = create(EnvironmentAttribute, environment=self, type=attrtype, value=value)
            session.add(attrib)
            self.attributes.append(attrib)
        session.commit()

    def get_attribute(self, session, attrname):
        attrtype = EnvironmentAttributeType.get_by_name(session, str(attrname))
        try:
            ea = session.query(EnvironmentAttribute).filter(and_(EnvironmentAttribute.environment==self, 
                            EnvironmentAttribute.type==attrtype)).one()
        except NoResultFound:
            raise ModelError("No attribute %r set." % (attrname,))
        return ea.value

    def del_attribute(self, session, attrtype):
        attrtype = EnvironmentAttributeType.get_by_name(session, str(attrtype))
        attrib = session.query(EnvironmentAttribute).filter(and_(
                EnvironmentAttribute.environment==self, EnvironmentAttribute.type==attrtype)).scalar()
        if attrib:
            self.attributes.remove(attrib)
        session.commit()

    @staticmethod
    def get_attribute_list(session):
        return EnvironmentAttributeType.get_attribute_list(session)

    equipment = association_proxy('testequipment', 'equipment')

    def get_equipment_with_role(self, session, rolename):
        role = session.query(SoftwareCategory).filter(SoftwareCategory.name == rolename).one()
        qq = session.query(TestEquipment).filter(and_(TestEquipment.environment==self,
                TestEquipment.roles.contains(role)))
        return qq.scalar().equipment

    def get_DUT(self, session):
        qq = session.query(TestEquipment).filter(and_(TestEquipment.environment==self,
                TestEquipment.UUT==True))
        return qq.scalar().equipment

    def get_supported_roles(self, session):
        rv = []
        for te in session.query(TestEquipment).filter(TestEquipment.environment==self).all():
            for role in te.roles:
                rv.append(role.name)
        rv = removedups(rv)
        return rv


mapper(Environment, tables.environments,
    properties={
        "owner": relation(User),
    },
)

class TestEquipment(object):
    """Binds equipment and a test environment.
    Also specifies the unit under test.
    """
    ROW_DISPLAY = ("equipment", "UUT")

    def __repr__(self):
        if self.UUT:
            return self.equipment.name + " (DUT)"
        else:
            return self.equipment.name

mapper(TestEquipment, tables.testequipment,
    properties={
        "roles": relation(SoftwareCategory, secondary=tables.testequipment_roles),
        "equipment": relation(Equipment),
        "environment": relation(Environment, backref="testequipment"),
    },
)


class EnvironmentAttribute(object):
    ROW_DISPLAY = ("type", "value")

    def __repr__(self):
        return "%s=%s" % (self.type, self.value)

    @validates("value")
    def validate_value(self, attrname, value):
        return validate_value_type(self.type.value_type, value)

mapper(EnvironmentAttribute, tables.environment_attributes,
    properties={
            "environment": relation(Environment, backref=backref("attributes", 
                    cascade="all, delete, delete-orphan")),
            "type": relation(EnvironmentAttributeType),
    },
)



#######################################
# trap storage

class Trap(object):
    ROW_DISPLAY = ("timestamp", "value")
    def __init__(self, timestamp, trap):
        self.timestamp = timestamp
        self.trap = trap # pickled

    def __str__(self):
        return "%s: %s" % (self.timestamp, self.trap)

mapper(Trap, tables.traps)


#######################################

#######################################
# Test relations and results

class TestCase(object):
    ROW_DISPLAY = ("name", "purpose", "testimplementation")

    def __str__(self):
        return str(self.name)

    def __repr__(self):
        return "TestCase(%r)" % (self.name,)

    def get_latest_result(self, session):
        sq = session.query(func.max(TestResult.starttime)).filter(and_(
                TestResult.testcase==self, 
                TestResult.valid==True)).subquery()
        return session.query(TestResult).filter(and_(
                TestResult.starttime==sq,
                TestResult.testcase==self,
                    )).scalar()

mapper(TestCase, tables.test_cases,
    properties={
        "functionalarea": relation(FunctionalArea, secondary=tables.test_cases_areas),
        "dependents": relation(TestCase, backref=backref("prerequisite",
                                remote_side=[tables.test_cases.c.id])),
    },
)


class TestSuite(object):
    ROW_DISPLAY = ("name", "suiteimplementation")

    def __str__(self):
        return str(self.name)

    def __repr__(self):
        return "TestSuite(%r)" % (self.name,)

mapper(TestSuite, tables.test_suites,
    properties={
        "project": relation(Project),
        "components": relation(Component, secondary=tables.components_suites, backref="suites"),
        "testcases": relation(TestCase, secondary=tables.test_suites_testcases, backref="suites"),
        "subsuites": relation(TestSuite, secondary=tables.test_suites_suites, 
            primaryjoin=tables.test_suites.c.id==tables.test_suites_suites.c.from_testsuite_id,
            secondaryjoin=tables.test_suites_suites.c.to_testsuite_id==tables.test_suites.c.id,
            backref="suites"),
    },
)


class TestJob(object):
    ROW_DISPLAY = ("name", "schedule")

    def __str__(self):
        return str(self.name)

    def __repr__(self):
        return "TestJob(%r)" % (self.name,)

mapper(TestJob, tables.test_jobs,
    properties = {
        "user": relation(User),
        "environment": relation(Environment, order_by=tables.environments.c.name),
        "suite": relation(TestSuite),
        "schedule": relation(Schedule),
    }
)


class TestResultData(object):
    ROW_DISPLAY = ("note",)

    def __str__(self):
        return "TestResultData: note: %r" % (self.note,)

    def __repr__(self):
        return "TestResultData(%r, %r)" % (self.data, self.note)

mapper(TestResultData, tables.test_results_data)


class TestResult(object):
    ROW_DISPLAY = ("testcase", "testimplementation", "tester", "result", "starttime")
    def __init__(self, **kwargs):
        for name, value in kwargs.items():
             setattr(self, name, value)

    def __str__(self):
                            #"TestSuite", "Test"
        if self.objecttype in (1, 2):
            if self.testcase is None:
                return "%s(%s): %s" % (self.testimplementation, self.objecttype, self.result)
            else:
                return "%s(%s): %s" % (self.testcase, self.objecttype, self.result)
        else:
            return "%s: %s" % (self.objecttype, self.result)

    def __repr__(self):
        return "TestResult(testimplementation=%r, objecttype=%r, result=%r)" % (
                self.testimplementation, self.objecttype, self.result)

    @classmethod
    def get_latest_results(cls, session, user=None):
        """Returns last 10 TestRunner (top-level) results.
        Optionally filtered by user.
        """
        if user is None:
            filt = and_(cls.objecttype==OBJ_TESTRUNNER, cls.valid==True)
        else:
            filt = and_(cls.objecttype==OBJ_TESTRUNNER, cls.tester==user, cls.valid==True)
        return session.query(cls).filter(filt).order_by(cls.starttime).limit(10).all()

    @classmethod
    def get_latest_run(cls, session, user):
        """Return the last Runner (top-level) TestResult for the User."""
        sq = session.query(func.max(cls.starttime)).filter(and_(
                cls.tester==user, 
                cls.objecttype==OBJ_TESTRUNNER, 
                cls.valid==True)).subquery()
        return session.query(cls).filter(and_(
                cls.starttime==sq,
                cls.tester==user, 
                cls.objecttype==OBJ_TESTRUNNER)).scalar()


mapper(TestResult, tables.test_results,
    properties = {
        "tester": relation(User),
        "data": relation(TestResultData),
        "environment": relation(Environment, order_by=tables.environments.c.name),
        "testcase": relation(TestCase),
        "build": relation(ProjectVersion),
        "subresults": relation(TestResult, backref=backref("parent",
                                remote_side=[tables.test_results.c.id])),
    }
)



#######################################
# capabilities for hardware

class CapabilityGroup(object):
    ROW_DISPLAY = ("name",)

    def __str__(self):
        return str(self.name)

mapper(CapabilityGroup, tables.capability_group)


class CapabilityType(object):
    ROW_DISPLAY = ("name", "value_type", "description", "group")

    def __str__(self):
        return "%s(%s)" % (self.name, self.value_type)

mapper(CapabilityType, tables.capability_type,
    properties={
        "group": relation(CapabilityGroup),
    }
)


class Capability(object):
    ROW_DISPLAY = ("type", "value")

    def __repr__(self):
        return "%s=%s" % (self.type, self.value)

    @validates("value")
    def validate_value(self, attrname, value):
        return validate_value_type(self.type.value_type, value)

mapper(Capability, tables.capability,
    properties={
        "type": relation(CapabilityType),
        "equipment": relation(Equipment, backref=backref("capabilities", 
                    cascade="all, delete, delete-orphan")),
    }
)


#######################################
# configuration data. This models a hierarchical storage structures. It
# should be updated with the pycopia.db.config wrapper objects.

class Config(object):
    ROW_DISPLAY = ("name", "value", "user", "testcase", "testsuite")

    def __str__(self):
        if self.value is NULL:
            return "[%s]" % self.name
        else:
            return "%s=%r" % (self.name, self.value)

    def __repr__(self):
        return "Config(%r, %r)" % (self.name, self.value)


mapper(Config, tables.config, 
    properties={
        'children': relation(Config, cascade="all", 
            backref=backref("container", 
                    remote_side=[tables.config.c.id, tables.config.c.user_id])),
        'testcase': relation(TestCase),
        'testsuite': relation(TestSuite),
        'user': relation(User),
    }
)


#######################################
# Basic address book table. This table originally mapped to
# StarOffice Addresses database and is here just for nostalgia. ;-)

class AddressBookEntry(object):
    pass
mapper(AddressBookEntry, tables.addressbook)



#######################################
## Utility functions
#######################################

def class_names():
    for mapper in _mapper_registry:
        yield mapper._identity_class.__name__


def get_choices(session, modelclass, colname, order_by=None):
    """Get possible choices for a field.

    Returns a list of tuples, (id/value, name/label) of available choices.
    """

    # first check for column type with get_choices method.
    mapper = class_mapper(modelclass)
    try:
        return mapper.columns[colname].type.get_choices()
    except (AttributeError, KeyError):
        pass
    mycol = getattr(modelclass, colname)
    try:
        relmodel = mycol.property.mapper.class_
    except AttributeError:
        return []

    # no choices in type, but has a related model table...
    mymeta = get_column_metadata(modelclass, colname)
    if mymeta.uselist:
        if mymeta.m2m:
            q = session.query(relmodel)
        else:
            # only those that are currently unassigned
            rs = mycol.property.remote_side[0]
            q = session.query(relmodel).filter(rs == None)
    else:
        q = session.query(relmodel)

    # add optional order_by, default to ordering by first ROW_DISPLAY column.
    try:
        order_by = order_by or relmodel.ROW_DISPLAY[0]
    except (AttributeError, IndexError):
        pass
    if order_by:
        q = q.order_by(getattr(relmodel, order_by))
    # Return the list of (id, stringrep) tuples.
    # This structure is usable by the XHTML form generator...
    return [(relrow.id, relrow) for relrow in q]


# structure returned by get_metadata function.
MetaDataTuple = collections.namedtuple("MetaDataTuple", 
        "coltype, colname, default, m2m, nullable, uselist, collection")


def get_metadata_iterator(class_):
    for prop in class_mapper(class_).iterate_properties:
        name = prop.key
        if name.startswith("_") or name == "id" or name.endswith("_id"):
            continue
        md = _get_column_metadata(prop)
        if md is None:
            continue
        yield md


def get_column_metadata(class_, colname):
    prop = class_mapper(class_).get_property(colname)
    md = _get_column_metadata(prop)
    if md is None:
        raise ValueError("Not a column name: %r." % (colname,))
    return md


def _get_column_metadata(prop):
    name = prop.key
    m2m = False
    default = None
    nullable = None
    uselist = False
    collection = None
    proptype = type(prop)
    if proptype is ColumnProperty:
        coltype = type(prop.columns[0].type).__name__
        try:
            default = prop.columns[0].default
        except AttributeError:
            default = None
        else:
            if default is not None:
                default = default.arg(None)
        nullable = prop.columns[0].nullable
    elif proptype is RelationshipProperty:
        coltype = RelationshipProperty.__name__
        m2m = prop.secondary is not None
        nullable = prop.local_side[0].nullable
        uselist = prop.uselist
        if prop.collection_class is not None:
            collection = type(prop.collection_class()).__name__
        else:
            collection = "list"
    else:
        return None
    return MetaDataTuple(coltype, str(name), default, m2m, nullable, uselist, collection)


def get_metadata(class_):
    """Returns a list of MetaDataTuple structures.
    """
    return list(get_metadata_iterator(class_))


def get_metadata_map(class_):
    rv = {}
    for metadata in get_metadata_iterator(class_):
        rv[metadata.colname] = metadata
    return rv


def get_rowdisplay(class_):
    return getattr(class_, "ROW_DISPLAY", None) or [t.colname for t in get_metadata(class_)]


if __name__ == "__main__":
    import sys
    import os
    from pycopia import autodebug
    if sys.flags.interactive:
        from pycopia import interactive
    prop = class_mapper(Equipment).get_property("interfaces")
    print prop
    print get_metadata(Equipment)
    print get_column_metadata(Equipment, "interfaces")
    print get_column_metadata(Network, "interfaces")
    sess = get_session()

    #choices = get_choices(sess, Equipment, "interfaces", order_by=None)
    #print choices
    choices = get_choices(sess, TestCase, "priority", order_by=None)
    print choices

    # assumes your host name is in the db for testing.
    eq = sess.query(Equipment).filter(Equipment.name.like(os.uname()[1] + "%")).one()
    #print "eq = ", eq
    #print "Atributes:"
    #print eq.attributes
    #print "Interfaces:"
    #print eq.interfaces
    #eq.add_interface(sess, "eth1", interface_type="ethernetCsmacd", ipaddr="172.17.101.2/24")
#    print "Capabilities:"
#    print eq.capabilities

#    for res in  TestResult.get_latest_results(sess):
#        print res

#    print "\nlatest run:"
#    user = User.get_by_username(sess, "keith")
#    lr = TestResult.get_latest_run(sess, user)
#    print lr
#    print
    #print dir(class_mapper(Equipment))
    #print
    #print class_mapper(Equipment).get_property("name")


