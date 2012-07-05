# Ant
#
# Copyright (c) 2012, Gustav Tiger <gustav@tiger.name>
#
# Permission is hereby granted, free of charge, to any person obtaining a
# copy of this software and associated documentation files (the "Software"),
# to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense,
# and/or sell copies of the Software, and to permit persons to whom the
# Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.

import array
import collections
import threading
import logging

from base import Ant, Message

_logger = logging.getLogger("garmin.ant.easy")

class EasyAnt(Ant):
    
    def __init__(self, idVendor, idProduct):
        Ant.__init__(self, idVendor, idProduct)
        
        self._responses_cond = threading.Condition()
        self._responses      = collections.deque()
        self._event_cond     = threading.Condition()
        self._events         = collections.deque()
        
        self.burst_data      = array.array('B', [])
        
        self.start()

    def response_function(self, message):
        self._responses_cond.acquire()
        self._responses.append(message)
        self._responses_cond.notify()
        self._responses_cond.release()
    
    def channel_event_function(self, message):
    
        if message._id == Message.ID.BURST_TRANSFER_DATA:

            sequence = message._data[0] >> 5
            channel  = message._data[0] & 0b00011111
            data     = message._data[1:]
            
            self.burst_data.extend(data)
            
            # Last sequence
            if sequence >= 4:
                _logger.debug("Burst data: %s", self.burst_data)
                _logger.debug("            %s", reduce(lambda x, y: x + chr(y), self.burst_data, ""))
                #phase += 1
                #self.on_burst_data(burst_data)
                message._data = self.burst_data
                # Reset
                self.burst_data = array.array('B', [])
            else:
                #print "sequence", sequence, message._data[0]
                #assert sequence == burst_seq + 1 or (sequence == 0 and burst_seq & 0b100) or (sequence == 1 and burst_seq == 3)
                return
                
            #burst_seq  = sequence
    
        #elif message._id == Message.ID.BROADCAST_DATA:
            #self.on_broadcast_data(message._data[1:])
        
        _logger.debug("channel event function %r", message)
        self._event_cond.acquire()
        self._events.append(message)
        self._event_cond.notify()
        self._event_cond.release()

    def get_event(self):
        #print "getevent"
        if self._event_cond.acquire(False):
            #print "ge - acquired"
            if len(self._events) == 0:
                self._event_cond.wait()
            message = self._events.popleft()
            self._event_cond.release()
            return message
        else:
            #print "ge - not acquired"
            return None

    def _wait_for_message(self, match, process, queue, condition):
        """
        Wait for a specific message in the *queue* guarded by the *condition*
        matching the function *match* (which is a function that takes a
        message as a parameter and returns a boolean). The messages is
        processed by the *process* function before returning it.
        """
        _logger.debug("wait for message matching %r", match)
        condition.acquire()
        for _ in range(10):
            _logger.debug("looking for matching message in %r", queue)
            #_logger.debug("wait for response to %#02x, checking", mId)
            for message in queue:
                if match(message):
                    _logger.debug(" - response found %r", message)
                    queue.remove(message)
                    condition.release()
                    return process(message)
            _logger.debug(" - could not find response matching %r", match)
            condition.wait(1.0)
        raise Exception("Timedout while waiting for message");

    def wait_for_event(self, ok_codes, error_codes):
        def match(message):
            return (message._id == Message.ID.RESPONSE_CHANNEL
                   and (message._data[2] in ok_codes or
                   message._data[2] in error_codes))
        def process(message):
            if message._data[2] in ok_codes:
                return message
            else:
                raise Exception("Responded with error " + message._data[2])
        return self._wait_for_message(match, process, self._events,
               self._event_cond)


    def wait_for_response(self, id):
        """
        Waits for a response to a specific message sent by the channel response
        message, 0x40. It's exepcted to return RESPONSE_NO_ERROR, 0x00.
        """
        def match(message):
            return (message._id == Message.ID.RESPONSE_CHANNEL and
                   message._data[1] == id)

        def process(message):
            if message._data[2] == Message.Code.RESPONSE_NO_ERROR:
                return message
            else:
                raise Exception("Reseponded with error " + message._data[2])
        return self._wait_for_message(match, process, self._responses,
               self._responses_cond)

    def wait_for_special(self, id):
        """
        Waits for special responsens to messages such as Channel ID, ANT
        Version, etc. This does not throw any exceptions, besides timeouts.
        """
        def match(message):
            return message._id == id
        def process(message):
            return message
        return self._wait_for_message(match, process, self._responses,
               self._responses_cond)

    def request_message(self, channel, messageId):
        _logger.debug("requesting message %#02x", messageId)
        Ant.request_message(self, channel, messageId)
        _logger.debug("done requesting message %#02x", messageId)
        return self.wait_for_special(messageId)

    def reset_system(self):
        Ant.reset_system(self)
        return self.wait_for_special(Message.ID.STARTUP_MESSAGE)

    def assign_channel(self, channel, channelType, networkNumber):
        Ant.assign_channel(self, channel, channelType, networkNumber)
        return self.wait_for_response(Message.ID.ASSIGN_CHANNEL)
    
    def open_channel(self, channel):
        Ant.open_channel(self, channel)
        return self.wait_for_response(Message.ID.OPEN_CHANNEL)
    
    def set_channel_id(self, channel, deviceNum, deviceType, transmissionType):
        Ant.set_channel_id(self, channel, deviceNum, deviceType, transmissionType)
        return self.wait_for_response(Message.ID.SET_CHANNEL_ID)
    
    def set_channel_period(self, channel, messagePeriod):
        Ant.set_channel_period(self, channel, messagePeriod)
        return self.wait_for_response(Message.ID.SET_CHANNEL_PERIOD)
    
    def set_channel_search_timeout(self, channel, timeout):
        Ant.set_channel_search_timeout(self, channel, timeout)
        return self.wait_for_response(Message.ID.SET_CHANNEL_SEARCH_TIMEOUT)
    
    def set_channel_rf_freq(self, channel, rfFreq):
        Ant.set_channel_rf_freq(self, channel, rfFreq)
        return self.wait_for_response(Message.ID.SET_CHANNEL_RF_FREQ)
    
    def set_network_key(self, network, key):
        Ant.set_network_key(self, network, key)
        return self.wait_for_response(Message.ID.SET_NETWORK_KEY)

    def set_search_waveform(self, channel, waveform):
        Ant.set_search_waveform(self, channel, waveform)
        return self.wait_for_response(Message.ID.SET_SEARCH_WAVEFORM)

    def send_acknowledged_data(self, channel, broadcastData):
        _logger.debug("send acknowledged data %s", channel)
        Ant.send_acknowledged_data(self, channel, broadcastData)
        x = self.wait_for_event([Message.Code.EVENT_TRANSFER_TX_COMPLETED],
                                [Message.Code.EVENT_TRANSFER_TX_FAILED])
        _logger.debug("done sending acknowledged data %s", channel)
        return x

    def send_burst_transfer_packet(self, channelSeq, data, first):
        _logger.debug("send burst transfer packet %s", data)
        Ant.send_burst_transfer_packet(self, channelSeq, data, first)


    def send_burst_transfer(self, channel, data):
        _logger.debug("send burst transfer %s", channel)
        Ant.send_burst_transfer(self, channel, data)
        self.wait_for_event([Message.Code.EVENT_TRANSFER_TX_START],
                            [Message.Code.EVENT_TRANSFER_TX_FAILED])
        x = self.wait_for_event([Message.Code.EVENT_TRANSFER_TX_COMPLETED],
                                [Message.Code.EVENT_TRANSFER_TX_FAILED])
        _logger.debug("done sending burst transfer %s", channel)
        return x

    def gofix(self):
        while True:
            message = self.get_event()
            
            if message == None:
                time.sleep(1)
                _logger.debug("npk")
                continue
            
            if message._id == Message.ID.BURST_TRANSFER_DATA:
                self.on_burst_data(message._data)
            elif message._id == Message.ID.BROADCAST_DATA:
                self.on_broadcast_data(message._data)
            else:
                _logger.warning("MESSAGE UNKNOWN %s, %s", message._id, message._data)
                _logger.warning("                %s", message)

    def on_burst_data(self, data):
        pass
    
    def on_broadcast_data(self, data):
        pass
