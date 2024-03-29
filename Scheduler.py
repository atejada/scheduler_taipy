# Import your dependencies
from dotenv import load_dotenv
import os
from nylas import Client  # type: ignore
from taipy.gui import Gui, navigate, notify
import pendulum
from flask import Flask, redirect, session, request
import re
import time
from nylas.models.auth import URLForAuthenticationConfig
from nylas.models.availability import GetAvailabilityRequest
from nylas.models.auth import CodeExchangeRequest

flask_app = Flask(__name__)

# Global variables for the state
#email_address = ""
value = ""
schedules = {"available":''}

# Load your env variables
load_dotenv()

# Initialize an instance of the Nylas SDK using the client credentials
nylas = Client(
    api_key = os.environ.get("V3_API_KEY")
)

root_md=""
page1_md="""
# Welcome to Blag's Scheduler

<|Nyla_Space.png|image|>


<|Google.png|image|on_action=on_button_action|>
"""

page2_md = """
### Available dates and times

<|{value}|selector|lov={schedules.get("available")}|>

<|Setup meeting|button|on_action=on_schedule_action|>  

<|Log out|button|on_action=on_logout_action|>
"""

pages = {
     "/": root_md,
     "page1": page1_md,
     "page2": page2_md
}

@flask_app.route("/login/nylas/authorized")
def authorized():
    # Get the code generated by the hosted authentication
    code = request.args.get("code")
    # Exchange the code for a grant
    exchangeRequest = CodeExchangeRequest({"redirect_uri": "http://localhost:5000/login/nylas/authorized",
                                                                              "code": code,
                                                                              "client_id": os.environ.get("V3_CLIENT")})

    # Get the information from the grant
    exchange = nylas.auth.exchange_code_for_token(exchangeRequest)
    response, _ = nylas.grants.find(exchange.grant_id)
    # Create a session
    session.permanent = True
    # Fill session details    
    session["email_address"] = response.email
    session["grant_id"] = exchange.grant_id
    # Call the login function to load availability
    dummy = login(session.get("state"))
    # Call the page to display availability
    return redirect("http://localhost:5000/page2")

def login(state):
    # Give some time for the grant to setup
    time.sleep(3)
    date_time = []
    schedules["available"] = ""

    # Get the availability for both email accounts
    request_body = GetAvailabilityRequest(
        participants = [
            {
                "email": os.environ.get("GRANT_ID"),
                "calendar_ids": [
                    os.environ.get("GRANT_ID")
                ],
            },
            {
                "email": session["email_address"],
                "calendar_ids": [
                    session["email_address"]
                ],
            },            
        ],
        
        duration_minutes = 60,
    )
    
    # Get today’s date
    today = pendulum.now()
    # Day of the week
    dow = today.day_of_week
    # Our working days goes from 10:00am to 5:00pm
    # And we don't want days that already passed by
    for x in range(dow, 6):
        start_time = pendulum.local(today.year, today.month, today.day, today.hour, 0, 0).int_timestamp
        end_time = pendulum.local(today.year, today.month, today.day, 17, 0, 0).int_timestamp
        
        request_body["start_time"] = start_time
        request_body["end_time"] = end_time

        # Get the available spots
        availability, _request_ids = nylas.calendars.get_availability(request_body)
        # Add the following day
        today = today.add(days=1)
        # Find available times
        for slot in availability.time_slots:
           ts = pendulum.from_timestamp(slot.start_time, today.timezone.name).strftime("%m/%d/%Y at %H:%M")
           te = pendulum.from_timestamp(slot.end_time ,today.timezone.name).strftime("%H:%M")
           date_time.insert(len(date_time), ts + " to " + te)

    # Here are all the available spots
    schedules["available"] = date_time
    return date_time

def on_button_action(state):
    # Generate the hosted authentication page
    session.pop("email_address", None)
    config = URLForAuthenticationConfig({"client_id": os.environ.get("V3_CLIENT"), 
                                                                  "redirect_uri" : "http://localhost:5000/login/nylas/authorized",
                                                                  "scope":["https://www.googleapis.com/auth/calendar.readonly"]})
    url = nylas.auth.url_for_oauth2(config)
    session["state"] = state
    # And call it
    navigate(state, url)

def on_schedule_action(state):
    # Extract the dates from the selected slot  
    pattern = r"(\d{1,2}/\d{1,2}/\d{4}) at (\d{1,2}:\d{2}) to (\d{1,2}:\d{2})"
    match = re.search(pattern, state.value)
    date = match.group(1)
    date_parts = date.split('/')
    start_time = match.group(2)
    start_time_parts = start_time.split(':')
    end_time = match.group(3)
    end_time_parts = end_time.split(':')
    
    query_params = {"calendar_id": os.environ.get("GRANT_ID")}
    
    # Define the events details
    request_body = {
        "when": { 
            "start_time": pendulum.local(int(date_parts[2]), int(date_parts[0]), 
                                                         int(date_parts[1]), int(start_time_parts[0]), 0, 0).int_timestamp,
            "end_time": pendulum.local(int(date_parts[2]), int(date_parts[0]), 
                                                        int(date_parts[1]), int(end_time_parts[0]), 0, 0).int_timestamp,        
        },
        "title": "Meeting with Blag",
       "location": "Blag's Online Den",
        "description": f"You're meeting with Blag on {date} from {start_time} to {end_time}",
        "participants": [{
            "email": session["email_address"], 
          }]
    }
    
    # Create the event
    event = nylas.events.create(os.environ.get("GRANT_ID"), 
                 query_params = query_params, request_body = request_body).data
    # Display a message with the status of the event creation
    if event.id:
        date_time = login(state)
        state.schedules["available"] = date_time
        navigate(state, "page2")
        notify(state, 'info', "The event was created successfully")
    else:
      notify(state, 'info', "There was an error creating the event") 

def on_logout_action(state):
    # We're logging out. Destroy the grant and clear all sessions
    nylas.grants.destroy(session["grant_id"])
    session.pop("email_address", None)
    session.pop("grant_id", None)
    navigate(state, "/")
    
Gui(pages=pages, flask=flask_app).run()
