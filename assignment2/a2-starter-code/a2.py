"""CSC343 Assignment 2

=== CSC343 Winter 2024 ===
Department of Computer Science,
University of Toronto

This code is provided solely for the personal and private use of
students taking the CSC343 course at the University of Toronto.
Copying for purposes other than this use is expressly prohibited.
All forms of distribution of this code, whether as given or with
any changes, are expressly prohibited.

Authors: Diane Horton, Marina Tawfik, Jacqueline Smith

All of the files in this directory and all subdirectories are:
Copyright (c) 2024 Diane Horton and Jacqueline Smith

=== Module Description ===

This file contains the Library class and some simple testing functions.
"""
import psycopg2 as pg
import psycopg2.extensions as pg_ext
import psycopg2.extras as pg_extras
from typing import Optional, List
import subprocess
from datetime import datetime, timedelta


class Library:
    """A class that can work with data conforming to the schema
    in a2_library_schema.ddl.

    === Instance Attributes ===
    connection: connection to a PostgreSQL database of a library management
    system.

    Representation invariants:
    - The database to which connection is established conforms to the schema
      in a2_library_schema.ddl.
    """
    connection: Optional[pg_ext.connection]

    def __init__(self):
        """Initialize this Library instance, with no database connection yet.
        """
        self.connection = None

    def connect(self, dbname: str, username: str, password: str) -> bool:
        """Establish a connection to the database <dbname> using the
        username <username> and password <password>, and assign it to the
        instance attribute 'connection'. In addition, set the search path
        to library, public.

        Return True if the connection was made successfully, False otherwise.
        I.e., do NOT throw an error if making the connection fails.

        >>> ww = Library()
        >>> # The following example will only work if you change the dbname
        >>> # and password to your own credentials.
        >>> ww.connect("postgres", "postgres", "password")
        True
        >>> # In this example, the connection cannot be made.
        >>> ww.connect("invalid", "nonsense", "incorrect")
        False
        """
        try:
            self.connection = pg.connect(
                dbname=dbname, user=username, password=password,
                options="-c search_path=Library,public"
            )
            return True
        except pg.Error:
            return False

    def disconnect(self) -> bool:
        """Close the database connection.

        Return True if closing the connection was successful, False otherwise.
        I.e., do NOT throw an error if closing the connection failed.

        >>> a2 = Library()
        >>> # The following example will only work if you change the dbname
        >>> # and password to your own credentials.
        >>> a2.connect("postgres", "postgres", "password")
        True
        >>> a2.disconnect()
        True
        """
        try:
            if self.connection and not self.connection.closed:
                self.connection.close()
            return True
        except pg.Error:
            return False

    def search(self, last_name: str, branch: str) -> List[str]:
        """Return the titles of all holdings at the library with the unique code
        <branch>, by any contributor with the last name <last_name>.
        Return an empty list if no matches are found.
        If two different holdings happen to have the same title, return both
        titles.
        However, don't return the same holding twice.

        Your method must NOT throw an error. Return an empty list if an error
        occurs.
        """
        self.cursor = self.connection.cursor()
        try:
            query = """
                SELECT DISTINCT h.title 
                FROM holding AS h
                JOIN holdingcontributor AS hc ON h.id = hc.holding
                JOIN contributor AS c ON hc.contributor = c.id
                JOIN libraryholding AS lh ON h.id = lh.holding
                WHERE c.last_name = %s AND lh.library = %s;
            """
            self.cursor.execute(query, (last_name, branch))
            titles = [row[0] for row in self.cursor.fetchall()]
            return titles

        except pg.Error as ex:
            return []
        

    def register(self, card_number: str, event_id: int) -> bool:
        """Record the registration of the patron with the card number
        <card_number> signing up for the event identified by <event_id>.

        Return True iff
            (1) The card number and event ID provided are both valid
            (2) This patron is not already registered for this event
            (3) The patron is not already registered for an event that overlaps
        Otherwise, return False.
        
        Two events that are consecutive, e.g. one ends at 14:00:00 and the 
        other begins at 14:00:00, are not considered overlapping. 

        Return True if the operation was successful (as per the above criteria),
        and False otherwise. Your method must NOT throw an error.
        """
        self.cursor = self.connection.cursor()

        try:
            self.cursor.execute("SELECT EXISTS(SELECT 1 FROM patron WHERE card_number = %s);", (card_number,))
            if not self.cursor.fetchone()[0]:
                return False

            self.cursor.execute("SELECT EXISTS(SELECT 1 FROM eventschedule WHERE event = %s);", (event_id,))
            if not self.cursor.fetchone()[0]:
                return False
            
            self.cursor.execute("SELECT EXISTS(SELECT 1 FROM eventsignup WHERE patron = %s AND event = %s);", (card_number, event_id,))
            if self.cursor.fetchone()[0]:
                return False

            query1 = """
                    SELECT esi.patron, esc.edate, esc.event, esc.start_time, esc.end_time
                    FROM eventsignup esi
                    JOIN eventschedule esc
                    ON esi.event = esc.event
                    WHERE esi.patron = %s
                    ORDER BY esi.patron, esc.event, esc.start_time, esc.end_time;
            """
            self.cursor.execute(query1, (card_number,))
            patron_events = self.cursor.fetchall()

            query2 = """
                    SELECT event, edate, start_time, end_time
                    FROM eventschedule esc
                    WHERE event = %s;
            """
            self.cursor.execute(query2, (event_id,))
            event_time = self.cursor.fetchall()

            can_register = True

            for new_event in event_time:
                for registered_event in patron_events:
                    if new_event[1] == registered_event[1]:
                        new_start = new_event[2]
                        new_end = new_event[3]
                        reg_start = registered_event[3]
                        reg_end = registered_event[4]
                        if (new_start < reg_end and new_end > reg_start):
                            can_register = False
                            break

                if not can_register:
                    break
            
            if (can_register):
                self.cursor.execute("INSERT INTO eventsignup (patron, event) VALUES (%s, %s);", (card_number, event_id,))
                self.connection.commit()

            return can_register

        except pg.Error as ex:
            return False
        
        

    def return_item(self, checkout: int) -> float:
        """Record that the checked-out library item, with the checkout id
        <checkout> was returned at the current time and return the fines 
        incurred on that item.

        Do so by inserting a row in the Return table and updating the
        LibraryCatalogue table to indicate the revised number of copies
        available.

        Use the same due date rules as the SQL queries.

        The fines incurred are calculated as follows: for everyday overdue
        i.e. past the due date:
            books and audiobooks incur a $0.50 charge
            other holding types incur a $1.00 charge

        A return operation is considered successful iff all the following
        criteria are satisfied:
            (1) The checkout id <checkout> provided is valid.
            (2) A return has not already been recorded for this checkout.
            (3) Updating the LibraryCatalogue won't cause the number of
                available copies to exceed the number of holdings.

        If the return operation is successful, make all necessary modifications
        (indicated above) and return the amount of fines incurred.
        Otherwise, the db instance should NOT be modified at all and a value of
        -1.0 should be returned. Your method must NOT throw an error.
        """
        self.cursor = self.connection.cursor()
        try:
            self.cursor.execute("SELECT EXISTS(SELECT 1 FROM checkout WHERE id = %s);", (checkout,))
            if not self.cursor.fetchone()[0]:
                return -1.0

            self.cursor.execute("SELECT EXISTS(SELECT 1 FROM return WHERE checkout = %s);", (checkout,))
            if self.cursor.fetchone()[0]:
                return -1.0
            query1 = """
                    SELECT c.id, 
                        c.checkout_time,
                        NOW() AS current_time,
                        h.htype,
                        CASE 
                            WHEN h.htype IN ('books', 'audiobooks') THEN EXTRACT(DAY FROM CURRENT_DATE - (c.checkout_time + INTERVAL '21 days'))
                            WHEN h.htype IN ('movies', 'music', 'magazines and newspapers') THEN EXTRACT(DAY FROM CURRENT_DATE - (c.checkout_time + INTERVAL '7 days'))
                        END AS overdue
                    FROM checkout c
                    JOIN libraryholding lh ON c.copy = lh.barcode
                    JOIN holding h ON lh.holding = h.id
                    WHERE c.id = %s;
            """
            self.cursor.execute(query1, (checkout,))
            result = self.cursor.fetchone()

            holding_type = result[3]
            overdue_days = max(0,result[4])
            fine_per_day = 0.50 if holding_type in ['books', 'audiobooks'] else 1.00
            fines = overdue_days * fine_per_day

            self.cursor.execute("INSERT INTO return (checkout, return_time) VALUES (%s, %s);", (checkout, result[2],))
            self.connection.commit()
            return fines
        
        except pg.Error as ex:
            return 10086

def test_preliminary() -> None:
    """Test preliminary aspects of the A2 methods.
    
    We have provided this function to you to give you some examples of what
    testing your code could look like. You should do much more thorough testing
    yourself before submitting to make sure your code works correctly. 
    """
    # TODO: Change the values of the following variables to connect to your
    #  own database:
    dbname = ""
    user = ""
    password = ""

    a2 = Library()
    try:
        connected = a2.connect(dbname, user, password)



        # The following is an assert statement. It checks that the value for
        # connected is True. The message after the comma will be printed if
        # that is not the case (connected is False).
        # Use the same notation to thoroughly test the methods we have provided
        assert connected, f"[Connect] Expected True | Got {connected}."

        # TODO: Test one or more methods here, or better yet, make more testing
        #   functions, with each testing a different aspect of the code.

        # The following function will set up the testing environment by loading
        # a fresh copy of the schema and the sample data we have provided into
        # your database. You can create more sample data files and use the same
        # function to load them into your database.

        # ------------------------- Testing search ----------------------------#

        expected_titles = ["Willy Wonka and the chocolate factory"]
        returned_titles = a2.search("Stuart", "DM")
        # We don't really need to use set here, but you might find it useful
        # in your own testing since we don't care about the order of the
        # returned items.
        assert set(returned_titles) == set(expected_titles), \
            f"[Search] Expected:\n{expected_titles}\n Got:\n{returned_titles}"

        # ------------------------ Testing register ---------------------------#

        # Invalid card number, valid event id
        # You should also check that no modifications were made to the db
        registered = a2.register("00000000000000000001", 1)
        assert not registered, "[Register] Invalid card number, valid " \
                               "event id: should return False. " \
                               f"Returned {registered}"
        # Valid card number, Invalid event id
        # You should also check that no modifications were made to the db
        registered = a2.register("5309015788", 200)
        assert not registered, "[Register] Valid card number, Invalid " \
                               "event id: should return False. " \
                               f"Returned {registered}"
        # Valid card number and event id
        # You should also check that the following row has been added to
        # the EventSignup relation:
        registered = a2.register("02953575718", 77)
        assert registered, "[Register] Valid card number, valid event id: " \
                           f"should return True. Returned {registered}"

        # ----------------------- Testing return_item -------------------------#

        # Invalid checkout id
        # You should also check that no modifications were made to the db
        returned = a2.return_item(1)
        assert returned == -1.0, "[Return] Invalid checkout id:" \
                                 f"should return -1.0. Returned {returned}"

        # Valid checkout id, but has already been returned
        returned = a2.return_item(94)
        assert returned == -1.0, "[Return] Already returned checkout id:" \
                                 f"should return -1.0. Returned {returned}"

    finally:
        a2.disconnect()


if __name__ == '__main__':
    # Un comment-out the next two lines if you would like to run the doctest
    # examples (see ">>>" in the methods connect and disconnect)
    # import doctest
    # doctest.testmod()

    # TODO: Put your testing code here, or call testing functions such as
    #   this one:
    test_preliminary()
