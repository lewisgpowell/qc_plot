#!/usr/bin/env python
"""
Wrappers around SQL queries and qcodes functions to load data and metadata
from a qcodes database
"""

import sqlite3
import numpy as np
import pandas as pd
from qcodes.dataset import load_by_run_spec

def get_independent_parameters(run_id, conn):
    """Get a list of independent parameters from a database

    Parameters:
    run_id (int): qcodes run id
    conn (qcodes.dataset.ConnectionPlus): qcodes sql connection

    Returns:
    A list of independent parameter name strings
    """
    dataset = load_by_run_spec(captured_run_id=run_id, conn=conn)
    return [p.name for p in dataset.get_parameters() if not p.depends_on]

def get_dependent_parameters(run_id, conn):
    """Get a list of dependent parameters from a database

    Parameters:
    run_id (int): qcodes run id
    conn (qcodes.dataset.ConnectionPlus): qcodes sql connection

    Returns:
    A list of dependent parameter name strings
    """
    dataset = load_by_run_spec(captured_run_id=run_id, conn=conn)
    return [p.name for p in dataset.get_parameters() if p.depends_on]

def get_result_table_name(run_id, conn):
    """Get the name of the SQL database table for a given qcodes run id

    Parameters:
    run_id (int): qcodes run id
    conn (qcodes.dataset.ConnectionPlus): qcodes sql connection

    Returns:
    A name of the table as a string
    """
    cur = conn.cursor()
    res = cur.execute(f"SELECT result_table_name FROM runs WHERE run_id={run_id}")
    data_table_name = res.fetchone()[0]
    return data_table_name

def get_most_recent_run_id(conn):
    """Get the most recent qcodes run id in the database

    Parameters:
    conn (qcodes.dataset.ConnectionPlus): qcodes sql connection

    Returns:
    The greatest run id in the database as an integer
    """
    cur = conn.cursor()
    res = cur.execute("SELECT MAX(run_id) FROM runs")
    most_recent_run_id = res.fetchone()[0]
    return most_recent_run_id

def convert_binary_to_complex(binary_string):
    """Decode binary strings to complex numbers"""
    return np.frombuffer(binary_string, dtype=complex)[-1]

def load_parameter_data(parameter, run_id, conn):
    """Get data for a given parameter and run id in a qcodes database as a pandas Series

    Parameters:
    parameter (string): qcodes parameter name
    run_id (int): qcodes run id
    conn (qcodes.dataset.ConnectionPlus): qcodes sql connection

    Returns:
    A pandas series containing data for a given dependent parameter and run id from the database.
    The indices of the sereies are the independent parameters for the run id.
    """
    result_table_name = get_result_table_name(run_id, conn)
    independent_parameters = get_independent_parameters(run_id, conn)

    parameter_data = pd.read_sql(f"SELECT {', '.join(independent_parameters)}, {parameter} "
    f"FROM '{result_table_name}' WHERE {parameter} IS NOT NULL", conn)
    parameter_data = parameter_data.set_index(independent_parameters).iloc[:, 0]

    # Convert complex values to numpy arrays
    if parameter_data.dtype == 'O':
        parameter_data = parameter_data.apply(convert_binary_to_complex)
    
    return parameter_data

def load_dataframe(run_id, conn):
    """Get data for all parameters corresponding to a particular run id in a qcodes database as a pandas DataFrame

    Parameters:
    run_id (int): qcodes run id
    conn (qcodes.dataset.ConnectionPlus): qcodes sql connection

    Returns:
    A Pandas series containing data on all independent parameters for the given run id.
    The indices of the sereies are the independent parameters for the run id.
    """
    dependent_parameters = get_dependent_parameters(run_id, conn)
    parameter_frames = [load_parameter_data(parameter, run_id, conn) for parameter in dependent_parameters]
    return pd.concat(parameter_frames, axis=1)