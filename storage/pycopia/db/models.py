#!/usr/bin/python
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

from datetime import datetime
from hashlib import sha1
import cPickle as pickle

from sqlalchemy import create_engine
from sqlalchemy.orm import (sessionmaker, mapper, relation, 
        backref, column_property, synonym, _mapper_registry)
from sqlalchemy.orm.collections import attribute_mapped_collection
from sqlalchemy.orm.exc import NoResultFound


from pycopia.aid import hexdigest, unhexdigest, Enums
from pycopia.db import tables


# type codes
OBJECT=0; STRING=1; UNICODE=2; INTEGER=3; FLOAT=4; BOOLEAN=5

# Test result types
OBJECTTYPES = Enums("module", "TestSuite", "Test", "TestRunner", "unknown")
[MODULE, SUITE, TEST, RUNNER, UNKNOWN] = OBJECTTYPES

# results a test case can produce.
TESTRESULTS = Enums(PASSED=1, FAILED=0, INCOMPLETE=-1, ABORT=-2, NA=-3, EXPECTED_FAIL=-4)
TESTRESULTS.sort()
[EXPECTED_FAIL, NA, ABORT, INCOMPLETE, FAILED, PASSED] = TESTRESULTS

def _get_secret():
    global SECRET_KEY
    from pycopia import basicconfig
    try:
        cf = basicconfig.get_config("auth.conf")
        SECRET_KEY = cf.SECRET_KEY
    except basicconfig.ConfigReadError:
        SECRET_KEY = "Testkey"
_get_secret()
del _get_secret



def create_session(addr):
    db = create_engine(addr)
    tables.metadata.bind = db
    return sessionmaker(bind=db)

def get_session(addr):
    session_class = create_session(addr)
    return session_class()

def get_config(url=None):
    if url is None:
        from pycopia import basicconfig
        cf = basicconfig.get_config("storage.conf")
        url = cf["database"]
    return get_session(url)


#######################################
# basic address book table. Table columns originally mapped to
# StarOffice Addresses database.

class AddressBookEntry(object):
    pass
mapper(AddressBookEntry, tables.addressbook)


#######################################
# USERS for ownership and web server authentication.

# maps generic authservice names in the DB to actual PAM service profiles
# provided by pycopia.
_SERVICEMAP = {
    None: None, # default to local-only auth
    "system": "pycopia",
    "ldap": "pycopia_ldap",
    "local": None,
}


class Permission(object):
    pass

mapper(Permission, tables.auth_permission)


class Group(object):
    pass

mapper(Group, tables.auth_group,
    properties={
        "permissions": relation(Permission, lazy=True, secondary=tables.auth_group_permissions),
    }
)


class UserMessage(object):
    def __unicode__(self):
        return self.message

mapper(UserMessage, tables.auth_message)


class User(object):
    def __init__(self, username=None, first_name=None, last_name=None, address=None, authservice="local",
            is_staff=True, is_active=True, is_superuser=False, last_login=None, date_joined=None):
        self.username = username
        self.first_name = first_name
        self.last_name = last_name
        self.address = address
        self.is_staff = is_staff
        self.is_active = is_active
        self.last_login = last_login
        self.date_joined = date_joined
        self.is_superuser = is_superuser
        self.authservice = authservice

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

    def get_session_key(self):
        h = sha1()
        h.update(str(self.id))
        h.update(self.username)
        h.update(str(self.last_login))
        return h.hexdigest()


def get_key():
    h = sha1()
    h.update(SECRET_KEY)
    h.update("ifucnrdthsurtoocls")
    return h.digest()[:16]


mapper(User, tables.auth_user,
    properties={
        "permissions": relation(Permission, lazy=True, secondary=tables.auth_user_user_permissions),
        "groups": relation(Group, lazy=True, secondary=tables.auth_user_groups),
        "messages": relation(UserMessage),
        "password": synonym('_password', map_column=True),
        "full_name": column_property( (tables.auth_user.c.first_name + " " + 
                tables.auth_user.c.last_name).label('full_name') ),
    })



def create_user(session, pwent):
  """Create a new user with a default password and name taken from the
  password entry (from the passwd module). 
  """
  now = datetime.now()
  fullname = pwent.gecos
  if fullname.find(",") > 0:
    [last, first] = fullname.split(",", 1)
  else:
    fnparts = fullname.split(None, 1)
    if len(fnparts) == 2:
      [first, last] = fnparts
    else:
      first, last = pwent.name, fnparts[0]
  grp = session.query(Group).filter(Group.name=="tester").one() # should already exist
  user = User(username=pwent.name, first_name=first, last_name=last, authservice="system",
      is_staff=True, is_active=True, last_login=now, date_joined=now)
  user.password = pwent.name + "123" # default, temporary password
  user.groups = [grp]
  session.add(user)
  session.commit()
  return user


# end USERS
#######################################

#######################################
# SESSIONS for web server sessions

class Cookie(object):
    pass

class Session(object):
    def __init__(self):
        self.session_data = pickle.dumps({})

    def _get_data(self):
        return pickle.loads(self.session_data)

    def _set_data(self, d):
        self.session_data = pickle.dumps(d)

    data = property(_get_data, _set_data)

    def __getitem__(self, key):
        return self._get_data()[key]

    def __setitem__(self, key, value):
        d = self._get_data()
        d[key] = value
        self._set_data(d)

    def __delitem__(self, key):
        d = self._get_data()
        del d[key]
        self._set_data(d)



mapper(Cookie, tables.cookies)

mapper(Session, tables.client_session,
#    properties={
#        "": synonym('_', map_column=True),
#    })
)

# end SESSIONS
#######################################

#######################################
# configuration data

class Config(object):

    def __init__(self, **kwargs):
        for name, value in kwargs.items():
            setattr(self, name, value)

    def _set_value(self, value):
        self.pickle = pickle.dumps(value)

    def _get_value(self):
        return pickle.loads(self.pickle)

    def _del_value(self):
        self.pickle = pickle.dumps(None)

    value = property(_get_value, _set_value, _del_value)

    def __str__(self):
        return "%s=%r" % (self.name, self.value)

mapper(Config, tables.config, properties={
    'children': relation(Config, backref=backref('container', remote_side=[tables.config.c.id]))
    })

#######################################

class Country(object):
    def __init__(self, name, isocode):
        self.name = name
        self.isocode = isocode

mapper(Country, tables.country_codes)


class CountrySet(object):
    pass

mapper(CountrySet, tables.country_sets,
    properties={
        "countries": relation(Country, lazy=True, secondary=tables.country_sets_countries),
    }
)


#######################################
# Misc

class LoginAccount(object):
    pass

mapper(LoginAccount, tables.account_ids)


class Language(object):
    def __init__(self, name, isocode):
        self.name = name
        self.isocode = isocode

mapper(Language, tables.language_codes)


class LanguageSet(object):
    pass

mapper(LanguageSet, tables.language_sets, 
    properties={
        "languages": relation(Language, lazy=True, secondary=tables.language_sets_languages),
    }
)

class Address(object):
    pass

mapper(Address, tables.addresses)


class Contact(object):
    pass

mapper(Contact, tables.contacts)


class Schedule(object):
    def __init__(self, name, minute="*", hour="*", day_of_month="*", month="*", day_of_week="*", user=None):
        self.name = name
        self.minute = minute
        self.hour = hour
        self.day_of_month = day_of_month
        self.month = month
        self.day_of_week = day_of_week
        if user is not None:
            self.user_id = user.id
        else:
            self.user_id = None


mapper(Schedule, tables.schedule)


class Location(object):
    pass

mapper(Location, tables.location)


#######################################
# capabilities and attributes

class CapabilityType(object):
    pass

mapper(CapabilityType, tables.capability_type)

class CapabilityGroup(object):
    pass

mapper(CapabilityGroup, tables.capability_group)

class Capability(object):
    pass

mapper(Capability, tables.capability)


class AttributeType(object):
    def __init__(self, name, vtype, description):
        self.name = name
        self.value_type_c = vtype
        self.description = description

mapper(AttributeType, tables.attribute_type)

#######################################
# projects

class ProjectCategory(object):
    pass

mapper(ProjectCategory, tables.project_category)


class FunctionalArea(object):
    def __init__(self, name, description):
        self.name = name
        self.description = description


mapper(FunctionalArea, tables.functional_area)


class Component(object):
    pass

mapper(Component, tables.components)



class BaseProject(object):
    pass

mapper(BaseProject, tables.projects,
    properties={
        "components": relation(Component, lazy=True, secondary=tables.projects_components),
    }
)


class Project(object):
    pass

mapper(Project, tables.project_versions)



#######################################
# Corporations

class CorporateAttributeType(object):
    pass
mapper(CorporateAttributeType, tables.corp_attribute_type)


class CorporateAttribute(object):
    pass
mapper(CorporateAttribute, tables.corp_attributes)


class Corporation(object):
    pass

mapper(Corporation, tables.corporations,
    properties={
        "services": relation(FunctionalArea, lazy=True, secondary=tables.corporations_services),
    }
)


#######################################
# Software model

# should also be called role or function
class SoftwareCategory(object):
    pass
mapper(SoftwareCategory, tables.software_category)


class SoftwareAttribute(object):
    pass

mapper(SoftwareAttribute, tables.software_attributes)


class Software(object):
    pass

class SoftwareVariant(object):
    pass
mapper(SoftwareVariant, tables.software_variant)

mapper (Software, tables.software,
    properties={
        "variants": relation(SoftwareVariant, lazy=True, secondary=tables.software_variants),
    }
)


#######################################
# Equipment model

# similar to ENTITY-MIB::PhysicalClass
class EquipmentCategory(object):
    def __init__(self, name):
        self.name = name

    def __str__(self):
        return "%s(%d)" % (self.name, self.id + 1)

mapper(EquipmentCategory, tables.equipment_category)

# IANAifType, minus obsolete and deprecated.
class InterfaceType(object):
    def __init__(self, name, enum):
        self.name = name
        self.enumeration = enum

    def __str__(self):
        return "%s(%d)" % (self.name, self.enumeration)

mapper(InterfaceType, tables.interface_type)

class Network(object):
    def __init__(self, name, ipnetwork=None, bridgeid=None, notes=None):
        self.name = name
        self.ipnetwork = ipnetwork.CIDR
        self.bridgeid = bridgeid
        self.notes = notes

    def __str__(self):
        if self.ipnetwork is not None:
            return "Net: %s (%s)" % (self.name, self.ipnetwork)
        elif bridgeid is not None:
            return "Net: %s: %s" % (self.name, self.bridgeid)
        else:
            return "Net: %s" % (self.name,)

mapper(Network, tables.networks)

class Interface(object):
    def __init__(self, name, alias=None, ifindex=None, description=None,
            macaddr=None, vlan=0, ipaddr=None, mtu=None, speed=None,
            status=0, iftype=None, equipment=None, network=None):
        self.name = name
        self.alias = alias
        self.ifindex = ifindex
        self.description = description
        self.macaddr = macaddr
        self.vlan = vlan
        self.ipaddr = ipaddr
        self.mtu = mtu
        self.speed = speed
        self.status = status
#interface_type_id
#parent_id
#equipment_id
#network_id

mapper(Interface, tables.interfaces)


class EquipmentModel(object):
    pass

mapper(EquipmentModel, tables.equipment_model,
    properties={
        "embeddedsoftware": relation(Software, secondary=tables.equipment_model_embeddedsoftware),
    }
)

class EquipmentModelAttribute(object):
    pass
mapper(EquipmentModelAttribute, tables.equipment_model_attributes)


class Equipment(object):
    pass

mapper(Equipment, tables.equipment,
    properties={
        "interfaces": relation(Interface, backref="equipment"),
        "subcomponents": relation(Equipment, backref=backref('parent', remote_side=[tables.equipment.c.id])),
        "software": relation(Software, lazy=True, secondary=tables.equipment_software),
    },
)


class EquipmentAttribute(object):

    def _get_value(self):
        return pickle.loads(self.pickle)

    def _set_value(self, value):
        self.pickle = pickle.dumps(value)

    def _del_value(self):
        self._set_value(None)

    value = property(_get_value, _set_value, _del_value)


mapper(EquipmentAttribute, tables.equipment_attributes,
    properties={
            "equipment": relation(Equipment, backref="attributes"),
    },
)

class EnvironAttributeType(object):
    pass

mapper(EnvironAttributeType, tables.environmentattribute_type)


class Environment(object):
    pass

mapper(Environment, tables.environments)

class EnvironmentAttribute(object):
    pass

mapper(EnvironmentAttribute, tables.environment_attributes)


class TestEquipment(object):
    """Binds equipment and a test environment.
    Also specifies the unit under test.
    """
    pass


mapper(TestEquipment, tables.testequipment,
    properties={
        "role": relation(SoftwareCategory, secondary=tables.testequipment_roles),
        "environment": relation(Environment, backref="testequipment"),
    },
)



#######################################
# trap storage

class Trap(object):
    def _get_value(self):
        return pickle.loads(self.pickle)

    def _set_value(self, obj):
        self.pickle = pickle.dumps(obj)

    value = property(_get_value, _set_value)


mapper(Trap, tables.traps)


#######################################

#######################################
# Test relations and results

class TestCase(object):
    pass

mapper(TestCase, tables.test_cases,
    properties={
        "functionalarea": relation(FunctionalArea, secondary=tables.test_cases_areas),
    },
)


class TestSuite(object):
    pass

mapper(TestSuite, tables.test_suites,
    properties={
        "testcases": relation(TestCase, secondary=tables.test_suites_testcases, backref="suite"),
        "components": relation(Component, secondary=tables.components_suites, backref="suites"),
#        TODO many-to-many join on self?
#        "subsuites": relation(TestSuite, 
#                        secondary=tables.test_suites_suites,
#                        primaryjoin=tables.test_suites_suites.c.from_testsuite_id==tables.test_suites.c.id,
#                        secondaryjoin=tables.test_suites_suites.c.to_testsuite_id==tables.test_suites.c.id,
#                    )
    },
)


class TestJob(object):
    pass

mapper(TestJob, tables.test_jobs)


class TestResultData(object):
    def __init__(self, data, note=None):
        self.pickle = pickle.dumps(data)
        self.note = note

mapper(TestResultData, tables.test_results_data)


class TestResult(object):
    def __init__(self, **kwargs):
        for name, value in kwargs.items():
            if name == "tester" and value is not None:
                self.tester_id = value.id
            elif name == "environment" and value is not None:
                #self.environment_id = value.id
                self.environment_id = None # TODO fix when there are proper environments in db
            elif name == "testcase" and value is not None:
                self.testcase_id = value.id
            elif name == "parent" and value is not None:
                self.parent_id = value.id
            else:
                setattr(self, name, value)

mapper(TestResult, tables.test_results)



#######################################


def class_names():
    for mapper in _mapper_registry:
        yield mapper._identity_class.__name__


if __name__ == "__main__":
    for cname in class_names():
        print cname


