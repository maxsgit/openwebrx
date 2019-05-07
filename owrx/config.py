import os

class Property(object):
    def __init__(self, value = None):
        self.value = value
        self.callbacks = []
    def getValue(self):
        return self.value
    def setValue(self, value):
        self.value = value
        for c in self.callbacks:
            try:
                c(self.value)
            except Exception as e:
                print(e)
        return self
    def wire(self, callback):
        self.callbacks.append(callback)
        if not self.value is None: callback(self.value)
        return self

class PropertyManager(object):
    sharedInstance = None
    @staticmethod
    def getSharedInstance():
        if PropertyManager.sharedInstance is None:
            PropertyManager.sharedInstance = PropertyManager()
        return PropertyManager.sharedInstance

    def collect(self, *props):
        return PropertyManager(dict((name, self.getProperty(name)) for name in props))

    def __init__(self, properties = None):
        self.properties = {}
        self.callbacks = []
        if properties is not None:
            for (name, prop) in properties.items():
                self.add(name, prop)

    def add(self, name, prop):
        self.properties[name] = prop
        def fireCallbacks(value):
            for c in self.callbacks:
                try:
                    c(name, value)
                except Exception as e:
                    print(e)
        prop.wire(fireCallbacks)
        return self

    def __getitem__(self, name):
        return self.getPropertyValue(name)

    def __setitem__(self, name, value):
        self.getProperty(name).setValue(value)

    def getProperty(self, name):
        if not name in self.properties:
            self.add(name, Property())
        return self.properties[name]

    def getPropertyValue(self, name):
        return self.getProperty(name).getValue()

    def wire(self, callback):
        self.callbacks.append(callback)
        return self

class RequirementMissingException(Exception):
    pass

class FeatureDetector(object):
    features = {
        "core": [ "csdr", "nmux" ],
        "rtl_sdr": [ "rtl_sdr" ],
        "sdrplay": [ "rx_tools" ],
        "hackrf": [ "hackrf_transfer" ]
    }

    def is_available(self, feature):
        return self.has_requirements(self.get_requirements(feature))

    def get_requirements(self, feature):
        return FeatureDetector.features[feature]

    def has_requirements(self, requirements):
        passed = True
        for requirement in requirements:
            methodname = "has_" + requirement
            if hasattr(self, methodname) and callable(getattr(self, methodname)):
                passed = passed and getattr(self, methodname)()
            else:
                print("detection of requirement {0} not implement. please fix in code!".format(requirement))
        return passed

    def has_csdr(self):
        return os.system("csdr 2> /dev/null") != 32512

    def has_nmux(self):
        return os.system("nmux --help 2> /dev/null") != 32512

    def has_rtl_sdr(self):
        return os.system("rtl_sdr --help 2> /dev/null") != 32512

    def has_rx_tools(self):
        return os.system("rx_sdr --help 2> /dev/null") != 32512

    def has_hackrf_transfer(self):
        # TODO i don't have a hackrf, so somebody doublecheck this.
        # TODO also check if it has the stdout feature
        return os.system("hackrf_transfer --help 2> /dev/null") != 32512
