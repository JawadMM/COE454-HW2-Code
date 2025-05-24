# HW2-1-client.py
# Smart Store Access System - Client Side
# Runs on ESP32-S3 with MicroPython

import time
import _thread
import network
from machine import Pin
import socket
import microcoapy

# WiFi Configuration
WIFI_SSID = ""
WIFI_PASSWORD = ""

# Server configuration
SERVER_IP = "172.20.10.10" 
SERVER_PORT = 5683  # Default CoAP port

# Configure pins
led = Pin(2, Pin.OUT)  # Built-in LED for indication
entry_button = Pin(12, Pin.IN, Pin.PULL_UP)  # Entry door trip sensor
exit_button = Pin(13, Pin.IN, Pin.PULL_UP)  # Exit door trip sensor

# Lock for thread synchronization
lock = _thread.allocate_lock()
coap_lock = _thread.allocate_lock()  # Lock for CoAP client access

# Global variables for button state tracking
last_entry_state = True  # Pull-up resistor means button is HIGH when not pressed
last_exit_state = True
debounce_time = 0.1  # seconds

# Global variables to store responses
last_response_payload = None
received_response = False

# Global CoAP client that will be shared between threads
coap_client = None

def connect_wifi(ssid, password):
    """Connect to WiFi network"""
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    
    if not wlan.isconnected():
        print(f"Connecting to WiFi network: {ssid}")
        wlan.connect(ssid, password)
        
        # Wait for connection with timeout
        max_wait = 10
        while max_wait > 0:
            if wlan.isconnected():
                break
            max_wait -= 1
            print("Waiting for connection...")
            time.sleep(1)
            
    if wlan.isconnected():
        print("WiFi connected")
        print(f"Network config: {wlan.ifconfig()}")
        return True
    else:
        print("WiFi connection failed")
        return False

def turn_led_green():
    """Turn LED on to simulate green light (door open)"""
    led.value(1)
    
def turn_led_red():
    """Turn LED off to simulate red light (door closed)"""
    led.value(0)
    
def coap_response_callback(packet, sender):
    """Callback for handling CoAP responses"""
    global last_response_payload, received_response
    
    print(f"Response received from {sender}")
    if packet and hasattr(packet, 'payload') and packet.payload:
        try:
            payload_text = packet.payload.decode()
            print(f"Payload: {payload_text}")
            last_response_payload = payload_text
        except:
            print(f"Raw payload: {packet.payload}")
            last_response_payload = packet.payload
    else:
        print("No payload in response")
        last_response_payload = None
    
    received_response = True

def entry_thread():
    """Thread handling the entry door sensor and communication"""
    global last_entry_state, coap_client, last_response_payload, received_response
    
    while True:
        current_state = entry_button.value()
        
        # Button pressed (LOW when pressed with pull-up)
        if current_state == 0 and last_entry_state == 1:
            print("Entry button pressed - requesting entry")
            
            # Reset the response flags
            last_response_payload = None
            received_response = False
            
            # Use the shared CoAP client with lock to prevent concurrent access
            with coap_lock:
                # Create request to check if entry is allowed
                messageId = coap_client.get(SERVER_IP, SERVER_PORT, "entry")
                
                # Wait for response with timeout
                timeout = time.time() + 5  # 5-second timeout
                while time.time() < timeout and not received_response:
                    coap_client.poll(500)  # Poll for responses
                    time.sleep(0.1)  # Short delay between polls
            
            # Process the response
            if received_response:
                if last_response_payload == "allowed":
                    print("Entry allowed")
                    with lock:
                        turn_led_green()
                        time.sleep(5)  # Door stays open for 5 seconds
                        turn_led_red()
                else:
                    print("Entry denied - store is at capacity")
                    # Blink LED to indicate denial
                    for _ in range(3):
                        with lock:
                            turn_led_green()
                            time.sleep(0.2)
                            turn_led_red()
                            time.sleep(0.2)
            else:
                print("No response from server")
                # Try accessing debug resource to test connectivity
                with coap_lock:
                    print("Trying debug resource...")
                    coap_client.get(SERVER_IP, SERVER_PORT, "debug")
                    time.sleep(2)  # Wait briefly for response
                    coap_client.poll(1000)
                
            # Debounce
            time.sleep(debounce_time)
            
        last_entry_state = current_state
        time.sleep(0.1)  # Short delay to prevent CPU hogging

def exit_thread():
    """Thread handling the exit door sensor and communication"""
    global last_exit_state, coap_client, last_response_payload, received_response
    
    while True:
        current_state = exit_button.value()
        
        # Button pressed (LOW when pressed with pull-up)
        if current_state == 0 and last_exit_state == 1:
            print("Exit button pressed - opening door and notifying server")
            
            # Open the door
            with lock:
                turn_led_green()
            
            # Reset the response flags
            last_response_payload = None
            received_response = False
            
            # Use the shared CoAP client with lock to prevent concurrent access
            with coap_lock:
                # Send exit notification
                print("Sending exit notification to server...")
                messageId = coap_client.put(SERVER_IP, SERVER_PORT, "exit", "customer_exit")
                print(f"Sent exit notification with message ID: {messageId}")
                
                # Wait for response with timeout
                timeout = time.time() + 3  # 3-second timeout
                while time.time() < timeout and not received_response:
                    coap_client.poll(500)  # Poll for responses
                    time.sleep(0.1)  # Short delay between polls
                
                # If no response, try alternative format
                if not received_response:
                    print("No response from server, trying with alternative path format...")
                    received_response = False
                    messageId = coap_client.put(SERVER_IP, SERVER_PORT, "/exit", "customer_exit")
                    print(f"Sent alternative exit notification with message ID: {messageId}")
                    
                    # Wait again
                    timeout = time.time() + 3
                    while time.time() < timeout and not received_response:
                        coap_client.poll(500)
                        time.sleep(0.1)
            
            # Keep door open for 5 seconds (minus any time spent waiting for response)
            remaining_time = max(0, 5 - (time.time() - (timeout - 3)))
            time.sleep(remaining_time)
            
            with lock:
                turn_led_red()
                
            # Debounce
            time.sleep(debounce_time)
            
        last_exit_state = current_state
        time.sleep(0.1)  # Short delay to prevent CPU hogging

def main():
    """Main function to start the client application"""
    global coap_client
    
    print("Starting Smart Store Access System Client...")
    
    # Connect to WiFi
    wifi_connected = connect_wifi(WIFI_SSID, WIFI_PASSWORD)
    if not wifi_connected:
        print("Cannot proceed without WiFi connection. Exiting...")
        return
    
    # Initialize LED to red (door closed)
    turn_led_red()
    
    # Create a single CoAP client instance to be shared between threads
    coap_client = microcoapy.Coap()
    coap_client.debug = True  # Enable debug output
    
    # Set the response callback
    coap_client.responseCallback = coap_response_callback
    
    coap_client.start()
    
    # Test server connectivity at startup
    print("Testing server connectivity...")
    test_result = coap_client.get(SERVER_IP, SERVER_PORT, "debug")
    if test_result > 0:
        print(f"Connection test successful, message ID: {test_result}")
        time.sleep(1)
        coap_client.poll(1000)  # Wait for response
    else:
        print(f"Warning: Server connection test failed")
    
    try:
        # Start entry and exit threads
        _thread.start_new_thread(entry_thread, ())
        _thread.start_new_thread(exit_thread, ())
        
        # Keep main thread alive
        while True:
            time.sleep(1)
            
    except Exception as e:
        print(f"Error: {e}")
    finally:
        # Clean up resources when exiting
        if coap_client:
            coap_client.stop()

if __name__ == "__main__":
    main()