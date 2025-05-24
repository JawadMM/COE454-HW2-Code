# HW2-1-server.py
# Smart Store Access System - Server Side with custom CoAP handling
# Runs on PC/laptop with standard Python

import time
import threading
import logging
import socket
import struct

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("CustomCoAPServer")

# Store statistics
class StoreStats:
    def __init__(self):
        self.total_entrants = 0
        self.customers_in_store = 0
        self.max_capacity = 10
        self.lock = threading.Lock()

    def display(self):
        """Display current store statistics"""
        remaining = self.max_capacity - self.customers_in_store
        print("\n----- Smart Store Access System -----")
        print(f"The total number of entrants:  {self.total_entrants}")
        print(f"Customers in the store:        {self.customers_in_store}")
        print(f"Remaining entries:             {remaining}")
        print("------------------------------------\n")

    def can_enter(self):
        """Check if a new customer can enter the store"""
        with self.lock:
            return self.customers_in_store < self.max_capacity

    def add_customer(self):
        """Add a customer to the store and update stats"""
        with self.lock:
            if self.customers_in_store < self.max_capacity:
                self.customers_in_store += 1
                self.total_entrants += 1
                return True
            return False

    def remove_customer(self):
        """Remove a customer from the store and update stats"""
        with self.lock:
            if self.customers_in_store > 0:
                self.customers_in_store -= 1
                return True
            return False

# CoAP Message Types
class CoAPType:
    CON = 0  # Confirmable
    NON = 1  # Non-confirmable
    ACK = 2  # Acknowledgement
    RST = 3  # Reset

# CoAP Method Codes
class CoAPCode:
    EMPTY = 0
    GET = 1
    POST = 2
    PUT = 3
    DELETE = 4
    
    # Response codes
    CREATED = 65  # 2.01
    DELETED = 66  # 2.02
    VALID = 67    # 2.03
    CHANGED = 68  # 2.04
    CONTENT = 69  # 2.05
    
    NOT_FOUND = 132  # 4.04
    METHOD_NOT_ALLOWED = 133  # 4.05
    
    INTERNAL_SERVER_ERROR = 160  # 5.00

# CoAP Option Numbers
class CoAPOption:
    URI_PATH = 11
    CONTENT_FORMAT = 12

# Simple CoAP message parser
class CoAPMessage:
    def __init__(self):
        self.version = 1
        self.type = 0
        self.token_length = 0
        self.code = 0
        self.message_id = 0
        self.token = b''
        self.options = []
        self.payload = b''
        self.source = None
        
    @staticmethod
    def parse(data):
        """Parse CoAP message from bytes"""
        if len(data) < 4:
            raise ValueError("Message too short")
            
        message = CoAPMessage()
        
        # Parse header
        header = struct.unpack('!BBH', data[:4])
        message.version = (header[0] >> 6) & 0x03
        message.type = (header[0] >> 4) & 0x03
        message.token_length = header[0] & 0x0F
        message.code = header[1]
        message.message_id = header[2]
        
        # Extract token
        if message.token_length > 0:
            message.token = data[4:4+message.token_length]
            
        # Parse options and payload
        pos = 4 + message.token_length
        option_number = 0
        
        while pos < len(data):
            if data[pos] == 0xFF:  # Payload marker
                pos += 1
                message.payload = data[pos:]
                break
                
            # Parse option
            option_delta = (data[pos] >> 4) & 0x0F
            option_length = data[pos] & 0x0F
            pos += 1
            
            # Extended option delta
            if option_delta == 13:
                option_delta = data[pos] + 13
                pos += 1
            elif option_delta == 14:
                option_delta = struct.unpack('!H', data[pos:pos+2])[0] + 269
                pos += 2
                
            # Extended option length
            if option_length == 13:
                option_length = data[pos] + 13
                pos += 1
            elif option_length == 14:
                option_length = struct.unpack('!H', data[pos:pos+2])[0] + 269
                pos += 2
                
            # Calculate option number
            option_number += option_delta
            
            # Get option value
            option_value = data[pos:pos+option_length]
            pos += option_length
            
            # Add option to list
            message.options.append((option_number, option_value))
            
        return message
    
    def create_response(self, code, payload=b''):
        """Create a response message"""
        response = CoAPMessage()
        response.version = 1
        response.type = CoAPType.ACK
        response.token_length = len(self.token)
        response.code = code
        response.message_id = self.message_id
        response.token = self.token
        response.payload = payload if isinstance(payload, bytes) else payload.encode('utf-8')
        return response
        
    def serialize(self):
        """Serialize CoAP message to bytes"""
        # Build header
        header = ((self.version & 0x03) << 6) | \
                ((self.type & 0x03) << 4) | \
                (self.token_length & 0x0F)
        
        data = struct.pack('!BBH', header, self.code, self.message_id)
        
        # Add token
        if self.token_length > 0:
            data += self.token
            
        # Add options
        current_option = 0
        for option in sorted(self.options):
            option_number, option_value = option
            
            # Calculate delta
            option_delta = option_number - current_option
            current_option = option_number
            
            # Option length
            option_length = len(option_value)
            
            # Option header
            option_header = ((option_delta & 0x0F) << 4) | (option_length & 0x0F)
            data += bytes([option_header])
            
            # Add option value
            data += option_value
            
        # Add payload
        if self.payload:
            data += b'\xFF'  # Payload marker
            data += self.payload
            
        return data
        
    def get_uri_path(self):
        """Get URI path from options"""
        uri_path = []
        for option in self.options:
            if option[0] == CoAPOption.URI_PATH:
                try:
                    uri_path.append(option[1].decode('utf-8'))
                except:
                    # If we can't decode, just use the raw bytes
                    uri_path.append(str(option[1]))
        
        return '/'.join(uri_path)
        
    def __str__(self):
        """String representation of the message"""
        if self.code == 0:
            code_str = "Empty"
        elif self.code <= 4:
            methods = ["Empty", "GET", "POST", "PUT", "DELETE"]
            code_str = methods[self.code]
        else:
            class_str = self.code >> 5
            detail_str = self.code & 0x1F
            code_str = f"{class_str}.{detail_str:02d}"
            
        type_str = ["CON", "NON", "ACK", "RST"][self.type]
        
        return f"CoAP {type_str} [{self.message_id}], {code_str}, " \
               f"Token: {self.token.hex()}, Path: {self.get_uri_path()}, " \
               f"Payload: {self.payload}"

# Custom CoAP Server
class CustomCoAPServer:
    def __init__(self, host='0.0.0.0', port=5683):
        self.host = host
        self.port = port
        self.socket = None
        self.running = False
        self.thread = None
        
    def start(self):
        """Start the server"""
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind((self.host, self.port))
        self.socket.settimeout(1)  # 1 second timeout
        
        self.running = True
        self.thread = threading.Thread(target=self.run)
        self.thread.start()
        
        logger.info(f"CoAP server started on {self.host}:{self.port}")
        
    def stop(self):
        """Stop the server"""
        self.running = False
        if self.thread:
            self.thread.join()
        if self.socket:
            self.socket.close()
        
        logger.info("CoAP server stopped")
        
    def run(self):
        """Main server loop"""
        while self.running:
            try:
                data, addr = self.socket.recvfrom(1024)
                logger.debug(f"Received {len(data)} bytes from {addr}")
                
                try:
                    # Parse the CoAP message
                    message = CoAPMessage.parse(data)
                    message.source = addr
                    
                    logger.info(f"Received message: {message}")
                    
                    # Handle the message
                    self.handle_message(message)
                    
                except Exception as e:
                    logger.exception(f"Error processing message: {e}")
                    
            except socket.timeout:
                # This is normal, just continue
                pass
            except Exception as e:
                logger.exception(f"Error in server loop: {e}")
                
    def send_response(self, message, code, payload=""):
        """Send a response to a message"""
        response = message.create_response(code, payload)
        logger.info(f"Sending response: {response}")
        
        self.socket.sendto(response.serialize(), message.source)
        
    def handle_message(self, message):
        """Handle a CoAP message (override in subclass)"""
        # Default implementation just echoes the message
        self.send_response(message, CoAPCode.CONTENT, "Echo")

# Smart Store CoAP Server
class SmartStoreServer(CustomCoAPServer):
    def __init__(self, host='0.0.0.0', port=5683):
        super().__init__(host, port)
        self.store_stats = StoreStats()
        
    def handle_message(self, message):
        """Handle CoAP messages for the smart store"""
        try:
            uri_path = message.get_uri_path()
            logger.info(f"Processing request for URI: {uri_path}")
            
            # Extract the path from options directly
            path = "unknown"
            for option in message.options:
                if option[0] == CoAPOption.URI_PATH:
                    try:
                        path = option[1].decode('utf-8')
                    except:
                        path = str(option[1])
                    logger.info(f"Found URI path: {path}")
            
            # Handle GET requests - entry
            if message.code == CoAPCode.GET:
                # Check for 'entry' in the path or option values
                is_entry = False
                if uri_path:
                    is_entry = "entry" in uri_path.lower()
                if not is_entry:
                    is_entry = path.lower() == "entry" or "entry" in path.lower()
                
                if is_entry:
                    self.handle_entry_request(message)
                else:
                    # Debug response for any other GET
                    logger.info("Sending debug response")
                    self.send_response(message, CoAPCode.CONTENT, "Debug response")
            
            # Handle PUT requests - exit
            elif message.code == CoAPCode.PUT:
                # Check for 'exit' in the path or option values
                is_exit = False
                if uri_path:
                    is_exit = "exit" in uri_path.lower()
                if not is_exit:
                    is_exit = path.lower() == "exit" or "exit" in path.lower()
                    
                if is_exit:
                    self.handle_exit_request(message)
                else:
                    # Debug response for any other PUT
                    logger.info("Sending debug PUT response")
                    self.send_response(message, CoAPCode.CHANGED, "Debug PUT response")
            
            # Any other method
            else:
                logger.info("Unsupported method")
                self.send_response(message, CoAPCode.METHOD_NOT_ALLOWED)
                
        except Exception as e:
            logger.exception(f"Error handling message: {e}")
            self.send_response(message, CoAPCode.INTERNAL_SERVER_ERROR, str(e))
    
    def handle_entry_request(self, message):
        """Handle an entry request"""
        logger.info("Handling entry request")
        
        if self.store_stats.can_enter():
            if self.store_stats.add_customer():
                logger.info("Entry allowed - customer added to store")
                self.send_response(message, CoAPCode.CONTENT, "allowed")
            else:
                logger.info("Entry denied - could not add customer")
                self.send_response(message, CoAPCode.CONTENT, "denied")
        else:
            logger.info("Entry denied - store at capacity")
            self.send_response(message, CoAPCode.CONTENT, "denied")
            
        self.store_stats.display()
    
    def handle_exit_request(self, message):
        """Handle an exit request"""
        logger.info("Handling exit request")
        
        if self.store_stats.remove_customer():
            logger.info("Customer successfully removed from store")
            self.send_response(message, CoAPCode.CHANGED, "success")
        else:
            logger.info("Error: No customers to remove from store")
            self.send_response(message, CoAPCode.CHANGED, "error")
            
        self.store_stats.display()

def main():
    print("Starting Smart Store Access System Server...")
    
    server = SmartStoreServer()
    server.start()
    
    try:
        # Keep the main thread alive
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Server shutdown by user")
    finally:
        server.stop()
        print("Server closed")

if __name__ == "__main__":
    main()