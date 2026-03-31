"use strict";

var QWebChannel = function(transport, initCallback) {
    if (typeof transport !== "object" || typeof transport.send !== "function") {
        console.error("QWebChannel: transport object is required and must have a send method!");
        return;
    }

    var channel = this;
    this.transport = transport;

    this.send = function(data) {
        if (typeof data !== "string") {
            data = JSON.stringify(data);
        }
        channel.transport.send(data);
    };

    this.transport.onmessage = function(message) {
        var data = message.data;
        if (typeof data === "string") {
            data = JSON.parse(data);
        }

        switch (data.type) {
            case 0: // init
                if (initCallback) {
                    for (var objectName in data.data) {
                        var object = new QObject(objectName, data.data[objectName], channel);
                        channel.objects[objectName] = object;
                    }
                    initCallback(channel);
                }
                break;
            case 1: // signal
                channel.handleSignal(data);
                break;
            case 2: // response
                channel.handleResponse(data);
                break;
            case 3: // property update
                channel.handlePropertyUpdate(data);
                break;
            default:
                console.error("QWebChannel: Invalid message type received:", data.type);
                break;
        }
    };

    this.execCallbacks = {};
    this.execId = 0;
    this.objects = {};

    this.handleSignal = function(message) {
        var object = channel.objects[message.object];
        if (object) {
            object.signalEmitted(message.signal, message.args);
        } else {
            console.warn("QWebChannel: Received signal for unknown object", message.object);
        }
    };

    this.handleResponse = function(message) {
        if (!message.id) {
            console.error("QWebChannel: Received response for message without id.");
            return;
        }
        var callback = channel.execCallbacks[message.id];
        if (callback) {
            callback(message.data);
            delete channel.execCallbacks[message.id];
        } else {
            console.warn("QWebChannel: Received response for unknown message", message.id);
        }
    };

    this.handlePropertyUpdate = function(message) {
        for (var i in message.data) {
            var data = message.data[i];
            var object = channel.objects[data.object];
            if (object) {
                object.propertyUpdate(data.signals, data.properties);
            } else {
                console.warn("QWebChannel: Received property update for unknown object", data.object);
            }
        }
    };

    this.exec = function(data, callback) {
        if (!callback) {
            channel.send(data);
            return;
        }
        if (channel.execId === Number.MAX_SAFE_INTEGER) {
            channel.execId = 0;
        }
        var id = ++channel.execId;
        channel.execCallbacks[id] = callback;
        data.id = id;
        channel.send(data);
    };

    this.getRegisteredObjects = function() {
        return Object.keys(channel.objects);
    };

    channel.exec({type: 0});
};

function QObject(name, data, webChannel) {
    this.__id__ = name;
    this.webChannel = webChannel;
    this.signals = {};
    this.properties = {};
    this.methods = {};

    var object = this;

    for (var i in data.properties) {
        var property = data.properties[i];
        this.properties[property] = {
            "value": undefined,
            "notify": null
        };
        if (property in data.values) {
            this.properties[property].value = data.values[property];
        }
        if (property + "Changed" in data.signals) {
            this.properties[property].notify = this.__id__ + "." + property + "Changed";
        }
        (function(name) {
            Object.defineProperty(object, name, {
                configurable: true,
                get: function() {
                    return object.properties[name].value;
                },
                set: function(value) {
                    if (value === object.properties[name].value) return;
                    object.properties[name].value = value;
                    object.webChannel.exec({
                        type: 4,
                        object: object.__id__,
                        property: name,
                        value: value
                    });
                }
            });
        })(property);
    }

    for (var i in data.signals) {
        var signal = data.signals[i];
        (function(name, signalData) {
            object.signals[name] = [];
            object[name] = {
                connect: function(callback) {
                    if (typeof callback !== "function") {
                        console.error("QWebChannel: Invalid callback given to connect to signal " + name);
                        return;
                    }
                    object.signals[name].push(callback);
                },
                disconnect: function(callback) {
                    var idx = object.signals[name].indexOf(callback);
                    if (idx !== -1) {
                        object.signals[name].splice(idx, 1);
                    } else {
                        console.error("QWebChannel: Unable to disconnect from signal " + name + " as the given callback is not connected.");
                    }
                }
            };
        })(signal, data.signals[signal]);
    }

    this.connectSignals = function() {
        for (var i in this.properties) {
            var prop = this.properties[i];
            if (prop.notify) {
                var signalName = prop.notify.split(".")[1];
                (function(name) {
                    object[signalName].connect(function(value) {
                        object.properties[name].value = value;
                    });
                })(i);
            }
        }
    };

    this.propertyUpdate = function(signals, propertyMap) {
        for (var propertyIdx in propertyMap) {
            this.properties[propertyIdx].value = propertyMap[propertyIdx];
        }
        for (var signalIdx in signals) {
            this.signalEmitted(signals[signalIdx][0], signals[signalIdx][1]);
        }
    };

    this.signalEmitted = function(signalName, signalArgs) {
        var connections = this.signals[signalName];
        if (connections) {
            connections.forEach(function(callback) {
                callback.apply(callback, signalArgs);
            });
        } else {
            console.warn("QWebChannel: Signal " + signalName + " emitted on object " + object.__id__ + ", but no connections found.");
        }
    };

    for (var i in data.methods) {
        var method = data.methods[i];
        (function(name, argCount) {
            object[name] = function() {
                var args = [];
                var callback;
                for (var i = 0; i < arguments.length; i++) {
                    if (typeof arguments[i] === "function")
                        callback = arguments[i];
                    else
                        args.push(arguments[i]);
                }
                if (args.length !== argCount) {
                    console.error("QWebChannel: Invalid number of arguments for method " + object.__id__ + "." + name + ". Expected " + argCount + ", got " + args.length);
                    return;
                }
                object.webChannel.exec({
                    type: 5,
                    object: object.__id__,
                    method: name,
                    args: args
                }, callback);
            };
        })(method[0], method[1]);
    }
    this.connectSignals();
}
