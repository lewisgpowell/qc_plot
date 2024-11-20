#!/usr/bin/env python
"""
Web interface for rapid live plotting of data from a qcodes database
"""

import os
import panel as pn
import param
import numpy as np
import pandas as pd
import hvplot.xarray
from time import sleep
from IPython.display import clear_output
from qcodes.dataset import ConnectionPlus, load_by_run_spec
import sqlite3
from functools import partial
from bokeh.core.serialization import DeserializationError
from load_data import load_parameter_data, get_independent_parameters, get_dependent_parameters, load_dataframe, get_most_recent_run_id

class PlotData(param.Parameterized):
    """The PlotData object connects to a database, stores relevant data and plots it as a
    holoviews figure

    Parameters:
    database_path (str): Optional path to the database to load when initialised

    Attributes:
    database_con (qcodes.dataset.ConnectionPlus): qcodes sql connection
    database_path (param.String): Path to the database
    run_id (param.Int): Qcodes run id for the experiment to plot
    plot_parameter (param.Selector): Dependent parameter to plot for the experiment
    data (param.Series): Data corresponding to the given run_id and plot_parameter
    show_imaginary (param.Boolean): If true, plots the real and immaginary parts of
    complex data. Otherwise, only plots the real part
    slice_along (param.Selector): Axis to take 1D cuts along for 2D data. Defaults
    to 'none'
    slice_vale (param.Selector): Value of axis slice_along on which to take cuts.
    fig: If plotting was successful, fig is a holoviews figure. Otherwise it is a
    string with error information
    """
    database_con = None
    database_path = param.String()
    run_id = param.Integer(default=1)
    plot_parameter = param.Selector()
    data = param.Series()
    show_imaginary = param.Boolean(False)
    slice_along = param.Selector(default='none')
    slice_value = param.Selector(default=None)
    fig = r'# Nothing to display'

    def __init__(self, database_path=None):
        super().__init__()
        if database_path:
            self.database_path = database_path
            self._connect_to_database()
        if self.database_con:
            self._update_parameters()
            self.update_data()

    def panel(self):
        """Required to display using panel"""
        return pn.panel(self.param)
    
    @param.depends('data', 'show_imaginary', 'slice_along', 'slice_value')
    def get_plot(self):
        """Getter for fig"""
        if self.database_con:
            return self.fig
    
    @param.depends('run_id', 'data')
    def get_info(self):
        """Returns the sample name, experiment name and experiment start time and formats it
        as a markdown string"""
        if self.database_con:
            try:
                dataset = load_by_run_spec(captured_run_id=self.run_id, conn=self.database_con)
                markdown_str = f"""
                # {dataset.sample_name}

                # {dataset.exp_name} run {dataset.captured_counter}

                # Started {dataset.run_timestamp()}
                """
                return markdown_str
            except NameError as e:
                return f"# {e}"
    
    @param.depends('database_path', watch=True)
    def _connect_to_database(self):
        """Connect to the qcodes database and set run_id to the most recent run id in
        the database"""
        try:
            if os.path.isfile(self.database_path):
                self.database_con = ConnectionPlus(sqlite3.connect(self.database_path))
                self.run_id = get_most_recent_run_id(self.database_con)
        except sqlite3.OperationalError:
            self.database_con = None
        except ValueError:
            self.run_id = 1
        except TypeError:
            self.database_con = None
    
    @param.depends('run_id', 'data', watch=True)
    def _update_parameters(self):
        """Read the independent and dependent parameters corresponding to run_id
        from the database and store them"""
        try:
            parameters = get_dependent_parameters(self.run_id, self.database_con)
            coordinate_names = get_independent_parameters(self.run_id, self.database_con)
            self.param['plot_parameter'].objects = parameters
            self.param['slice_along'].objects = ['none', *coordinate_names]
            if self.plot_parameter not in parameters:
                self.plot_parameter = parameters[0]
        except NameError:
            self.param['plot_parameter'].objects = []
            self.param['slice_along'].objects = []
        except TypeError:
            self.param['plot_parameter'].objects = []
            self.param['slice_along'].objects = []

    @param.depends('run_id', 'plot_parameter', watch=True)
    def update_data(self, **kwargs):
        """Read data for the selected run_id and plot_parameter and store it"""
        try:
            if self.database_con:
                self._update_parameters()
                self.data = load_parameter_data(self.plot_parameter, self.run_id, self.database_con)
            else:
                self._connect_to_database()
                self._update_parameters()
                self.data = load_parameter_data(self.plot_parameter, self.run_id, self.database_con)
        except NameError:
            self.data = None
        except TypeError:
            self.data = None
        except sqlite3.DatabaseError:
            self.data = None
    
    @param.depends('data', 'show_imaginary', 'slice_value', watch=True)
    def _update_plot(self):
        """Use the most appropriate function to plot real or complex data"""
        try:
            plot_data = self.__remove_unused_coords(self.data)
            if plot_data.dtype == 'complex':
                if self.show_imaginary:
                    self.fig = self.__plot_complex(plot_data, width=500, height=800)
                else:
                    self.fig = self.__plot_real(plot_data.apply(np.real), width=1000, height=800)
            else:
                self.fig = self.__plot_real(plot_data, width=1000, height=800)
        except Exception as e:
            self.fig = f"Error plotting: {e}"
    
    @param.depends('data', 'slice_along', watch=True)
    def _update_slice_options(self):
        """Find values on axis slice_along in which 1D cuts can be plotted"""
        if self.slice_along == 'none':
            self.slice_value = None
            self.param['slice_value'].objects = []
        else:
            values = self.data.index.get_level_values(self.slice_along).drop_duplicates().values
            self.param['slice_value'].objects = [*values]
            if self.slice_value not in values:
                self.slice_value = values[0]
        self._update_plot()

    def __plot_real(self, plot_data, **kwargs):
        """Plot 1D or 2D real data"""
        if plot_data.index.nlevels > 1:
            return self.__plot_2d(plot_data, **kwargs)
        else:
            return self.__plot_1d(plot_data, **kwargs)
    
    def __plot_complex(self, plot_data, **kwargs):
        """Plot 1D or 2D complex data"""
        return self.__plot_real(plot_data.apply(np.real), **kwargs) + self.__plot_real(plot_data.apply(np.imag), **kwargs)
    
    def __plot_2d(self, plot_data, **kwargs):
        """Plot 2D data using hvplot.xarray"""
        if self.slice_along == 'none':
            return plot_data.to_xarray().interpolate_na(dim=plot_data.index.names[-1]).hvplot.quadmesh(cmap='viridis', rasterize=True, **kwargs)
        else:
            return self.__plot_1d(plot_data.xs(self.slice_value, level=self.slice_along), **kwargs)

    def __plot_1d(self, plot_data, **kwargs):
        """Plot 1D data using hvplot.xarray"""
        xa = plot_data.to_xarray()
        return xa.hvplot.line(**kwargs) * xa.hvplot.scatter(s=20, **kwargs)

    def __remove_unused_coords(self, df):
        """Recursively trim any unused coordinates from a dataframe"""
        if df.index.get_level_values(0).drop_duplicates().size > 1 or df.index.nlevels == 1:
            return df
        else:
            return self.__remove_unused_coords(df.droplevel(0)) 
    

def update(plotter):
    """Callback to trigger the PlotData object to retrieve any new data and plot ita

    Parameters:
    plotter (PlotData): PlotData object to update
    """
    if plotter.slice_along != 'none':
        plotter.slice_value = plotter.param['slice_value'].objects[-1]
    plotter.update_data()

def panel_app(database_path=None):
    """Formats the plot and controls into a Panel layout to display as a web app

    Parameters:
    database_path (str): Optional path to the database when starting the web app

    Returns:
    A panel.Row containing the plot and associated widgets
    """
    plot_data = PlotData(database_path)
    refresh_plot = pn.state.add_periodic_callback(partial(update, plot_data), 3000, start=False)
    toggle = pn.widgets.Toggle(name='Refresh', value=False)
    toggle.link(refresh_plot, bidirectional=True, value='running')
    col1 = pn.Column(
        pn.Row(plot_data.param.database_path, plot_data.param.run_id, plot_data.param.plot_parameter),
        plot_data.get_plot,
        pn.Row(
            toggle,
            pn.Param(plot_data, widgets={'show_imaginary': {'type': pn.widgets.Toggle}}, parameters=["show_imaginary"], show_name=False),
        )
    )
    col2 = pn.Column(
        plot_data.get_info,
        plot_data.param.slice_along,
        plot_data.param.slice_value
    )
    row = pn.Row(col1, col2)
    return row

def serve_app(database_path=None):
    """Lanuch the web app"""
    return pn.serve(panel_app(database_path))

if __name__ == "__main__":
    try:
        pn.serve(panel_app)
    except DeserializationError:
        pass
