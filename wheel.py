#!/usr/bin/env python

'''
Pupil-wheel

Creates GUI to control behavioral devices for recording video (pupil) and rotary
encoder (wheel). Script interfaces with Arduino microcontroller and cameras.

Outline of flow
1. Set parameters for experiment.
2. Establish serial connection with Arduino. Paremeters will be uploaded to
Arduino when this happens.
3. Set meta data for experiment and saved file location.
4. Start experiment!

'''

import sys
sys.path.insert(0, './behavior')

import argparse
import tkinter as tk
import tkinter.ttk as ttk
import tkinter.font as tkFont
import tkinter.messagebox as tkMessageBox
import tkinter.filedialog as tkFileDialog
from tkinter.scrolledtext import ScrolledText
from PIL import ImageTk
import serial
import serial.tools.list_ports
import threading
from queue import Queue
import time
from datetime import datetime, timedelta
import os
import h5py
import numpy as np
import matplotlib
from matplotlib.figure import Figure
import arduino
import live_data_view
import pdb

matplotlib.use('TKAgg')


# Header to print with Arduino outputs
arduino_head = '  [a]: '

# Formatting
entry_width = 10
ew = 10  # Width of Entry UI
px = 15
py = 5
px1 = 5
py1 = 2

# Serial input codes
code_end = 0
code_wheel = 7

# Arduino code to save-file variable
arduino_events = {
    code_wheel: 'wheel'
}

# Events to count
# counter_ev =[]

# Path to this file
source_path = os.path.dirname(sys.argv[0])

class Main(tk.Frame):

    def __init__(self, parent, verbose=False, emulate_wheel=False, print_arduino=False):
        self.parent = parent
        parent.columnconfigure(0, weight=1)
        # parent.rowconfigure(1, weight=1)

        self.verbose = verbose

        self.var_cache_size = tk.IntVar()
        self.var_sess_dur = tk.IntVar()
        self.var_rec_zeros = tk.IntVar()
        self.var_emulate_wheel = tk.IntVar()
        self.var_track_per = tk.IntVar()
        self.var_save_txt = tk.BooleanVar()

        self.var_cache_size.set(500)
        self.var_sess_dur.set(1)
        self.var_rec_zeros.set(1)
        self.var_emulate_wheel.set(emulate_wheel)
        self.var_track_per.set(50)
        self.var_save_txt.set(True)

        self.parameters = {
            'emulate_wheel': self.var_emulate_wheel,
            'session_dur': self.var_sess_dur,
            'record_zeros': self.var_rec_zeros,
            'track_period': self.var_track_per,
        }

        self.var_print_arduino = tk.BooleanVar()
        self.var_stop = tk.BooleanVar()

        self.var_print_arduino.set(print_arduino)
        self.var_stop.set(False)

        # Counters
        # IMPORTANT: need to keep `counter_vars` in same order as `arduino_events`
        self.var_counter_wheel = tk.IntVar()
        counter_vars = [self.var_counter_wheel]
        self.counter = {ev: var_count for ev, var_count in zip(arduino_events.values(), counter_vars)}

        self.var_start_time = tk.StringVar()
        self.var_stop_time = tk.StringVar()

        # Lay out GUI

        frame_setup = tk.Frame(parent)
        frame_setup.grid(row=0, column=0)
        frame_setup_col0 = tk.Frame(frame_setup)
        frame_setup_col1 = tk.Frame(frame_setup)
        # frame_setup_col2 = tk.Frame(frame_setup)
        frame_setup_col0.grid(row=0, column=0, sticky='we')
        frame_setup_col1.grid(row=0, column=1, sticky='we')
        # frame_setup_col2.grid(row=0, column=2, sticky='we')

        frame_monitor = tk.Frame(parent)
        frame_monitor.grid(row=1, column=0)
        # frame_monitor.rowconfigure(0, weight=1)
        # frame_monitor.columnconfigure(1, weight=1)

        # Session frame
        frame_params = tk.Frame(frame_setup_col0)
        frame_params.grid(row=0, column=0, padx=15, pady=5)
        frame_params.columnconfigure(0, weight=1)

        frame_session = tk.Frame(frame_params)
        frame_misc = tk.Frame(frame_params)
        frame_session.grid(row=0, column=0, sticky='e', padx=px, pady=py)
        frame_misc.grid(row=2, column=0, sticky='e', padx=px, pady=py)
 
        # Arduino frame
        frame_arduino = ttk.LabelFrame(frame_setup_col0, text='Arduino')
        frame_arduino.grid(row=1, column=0, padx=px, pady=py, sticky='we')

        # Notes frame
        frame_notes = tk.Frame(frame_setup_col1)
        frame_notes.grid(row=0, sticky='wens', padx=px, pady=py)
        frame_notes.grid_columnconfigure(0, weight=1)

        # Saved file frame
        frame_file = tk.Frame(frame_setup_col1)
        frame_file.grid(row=1, column=0, padx=px, pady=py, sticky='we')
        frame_file.columnconfigure(0, weight=3)
        frame_file.columnconfigure(1, weight=1)

        # Start-stop frame
        frame_start = tk.Frame(frame_setup_col1)
        frame_start.grid(row=3, column=0, sticky='we', padx=px, pady=py)
        frame_start.grid_columnconfigure(0, weight=1)
        frame_start.grid_columnconfigure(1, weight=1)

        # Monitor frame
        frame_counter = tk.Frame(frame_monitor)
        frame_live = tk.Frame(frame_monitor)
        frame_counter.grid(row=0, column=0, padx=px, pady=py, sticky='we')
        frame_live.grid(row=1, column=0, padx=px, pady=py, sticky='wens')

        # Add GUI components

        ## frame_params

        ### frame_session
        ## UI for trial control
        self.entry_session_dur = ttk.Entry(frame_session, textvariable=self.var_sess_dur, width=entry_width)
        tk.Label(frame_session, text='Session duration (min): ', anchor='e').grid(row=0, column=0, sticky='e')
        self.entry_session_dur.grid(row=0, column=1, sticky='w')

        ### frame_misc
        ### UI for miscellaneous parameters
        self.entry_rec_all = ttk.Checkbutton(frame_misc, variable=self.var_rec_zeros)
        self.entry_track_period = ttk.Entry(frame_misc, textvariable=self.var_track_per, width=entry_width)
        tk.Label(frame_misc, text='Record zeros: ', anchor='e').grid(row=0, column=0, sticky='e')
        tk.Label(frame_misc, text='Track period (ms): ', anchor='e').grid(row=1, column=0, sticky='e')
        self.entry_rec_all.grid(row=0, column=1, sticky='w')
        self.entry_track_period.grid(row=1, column=1, sticky='w')

        ### frame_arduino
        ### UI for Arduino
        self.arduino = arduino.Arduino(frame_arduino, main_window=self.parent, verbose=self.verbose, params=self.parameters)
        self.arduino.grid(row=0, column=0, sticky='we')
        self.arduino.var_uploaded.trace_add('write', self.gui_util)

        ## Notes
        self.entry_subject = ttk.Entry(frame_notes)
        self.entry_weight = ttk.Entry(frame_notes)
        self.scrolled_notes = ScrolledText(frame_notes, width=20, height=15)
        tk.Label(frame_notes, text='Subject: ').grid(row=0, column=0, sticky='e')
        tk.Label(frame_notes, text='Weight (g): ').grid(row=1, column=0, sticky='e')
        tk.Label(frame_notes, text='Notes:').grid(row=2, column=0, columnspan=2, sticky='w')
        self.entry_subject.grid(row=0, column=1, sticky='w')
        self.entry_weight.grid(row=1, column=1, sticky='w')
        self.scrolled_notes.grid(row=3, column=0, columnspan=2, sticky='wens')

        ## UI for saved file
        self.entry_save_file = ttk.Entry(frame_file)
        self.button_set_file = ttk.Button(frame_file, command=self.get_save_file)
        tk.Label(frame_file, text='File to save data:', anchor='w').grid(row=0, column=0, columnspan=2, sticky='w')
        self.entry_save_file.grid(row=1, column=0, sticky='wens')
        self.button_set_file.grid(row=1, column=1, sticky='e')

        icon_folder = ImageTk.PhotoImage(file=os.path.join(source_path, 'behavior/graphics/folder.png'))
        self.button_set_file.config(image=icon_folder)
        self.button_set_file.image = icon_folder
        
        ## Start frame
        self.button_start = ttk.Button(frame_start, text='Start', command=lambda: self.parent.after(0, self.start))
        self.button_stop = ttk.Button(frame_start, text='Stop', command=lambda: self.var_stop.set(True))
        self.button_start.grid(row=2, column=0, sticky='we')
        self.button_stop.grid(row=2, column=1, sticky='we')

        ## Counter frame
        tk.Label(frame_counter, text='Start time: ').grid(row=0, column=0, sticky='e')
        tk.Label(frame_counter, text='End time: ').grid(row=1, column=0, sticky='e')
        self.entry_start_time = ttk.Entry(frame_counter, textvariable=self.var_start_time, state='readonly', width=entry_width)
        self.entry_stop_time = ttk.Entry(frame_counter, textvariable=self.var_stop_time, state='readonly', width=entry_width)
        self.entry_start_time.grid(row=0, column=1, sticky='wens')
        self.entry_stop_time.grid(row=1, column=1, sticky='wens')

        ## Live frame
        data_types = {
            arduino_events[code_wheel]: 'line'
        }
        # tk.Label(frame_live, text='Also under construction').grid()
        self.live_view = live_data_view.LiveDataView(
            frame_live, x_history=30000, scale_x=0.001,
            data_types=data_types, ylim=(-25, 50), xlabel='Time (s)'
        )
        
        ###### GUI OBJECTS ORGANIZED BY TIME ACTIVE ######
        # List of components to disable at open
        self.obj_to_disable_on_upload = [
            child for child in
            (frame_session.winfo_children() + frame_misc.winfo_children())
        ]
        self.obj_to_enable_on_upload = [self.button_start]
        self.obj_to_disable_at_open = [
            self.entry_session_dur,
            self.entry_track_period,
        ]
        
        self.obj_to_enable_at_open = [
            self.button_start,
        ]
        self.obj_to_disable_at_start = [
            self.entry_subject,
            self.entry_weight,
            self.entry_save_file,
            self.button_set_file,
            self.button_start,
        ]
        self.obj_to_enable_at_start = [
            self.button_stop
        ]

        # Default values
        self.button_start['state'] = 'disabled'
        self.button_stop['state'] = 'disabled'

        ###### SESSION VARIABLES ######
        self.q_serial = Queue()

        # self.update_serial()

    def get_save_file(self):
        ''' Opens prompt for file for data to be saved
        Runs when button beside save file is pressed.
        '''

        save_file = tkFileDialog.asksaveasfilename(
            initialdir=self.entry_save_file.get(),
            defaultextension='.h5',
            filetypes=[
                ('CSV file', '*.csv'),
                ('HDF5 file', '*.h5 *.hdf5'),
            ]
        )
        self.entry_save_file.delete(0, 'end')
        self.entry_save_file.insert(0, save_file)

    def gui_util(self, option, indx=None, mode=None):
        ''' Updates GUI components
        Enable and disable components based on events to prevent bad stuff.
        '''

        if option == 'start':
            for obj in self.obj_to_disable_at_start:
                obj['state'] = 'disabled'
            for obj in self.obj_to_enable_at_start:
                obj['state'] = 'normal'

        elif option == 'stop':
            for obj in self.obj_to_disable_at_start:
                obj['state'] = 'normal'
            for obj in self.obj_to_enable_at_start:
                obj['state'] = 'disabled'

        elif option == 'uploaded':
            new_state = 'disable' if self.parent.getvar('uploaded') else 'normal'
            for obj in self.obj_to_disable_on_upload:
                obj['state'] = new_state
            for obj in self.obj_to_enable_on_upload:
                obj['state'] = 'disable' if new_state == 'normal' else 'normal'
    
    def start(self, code_start='E'):
        self.gui_util('start')

        now = datetime.now()

        # Create default filename if not defined
        if not self.entry_save_file.get():
            # Default file name
            if not os.path.exists('data'):
                os.makedirs('data')

            if self.var_save_txt.get():
                ext = '.csv'
            else:
                ext = '.h5'
            filename = 'data/data-' + now.strftime('%y%m%d-%H%M%S') + ext
            state = self.entry_save_file['state']
            self.entry_save_file['state'] = 'normal'
            self.entry_save_file.delete(0, 'end')
            self.entry_save_file.insert(0, filename)
            self.entry_save_file['state'] = state
        else:
            if os.path.splitext(self.entry_save_file.get())[1] in ['.h5', '.hdf5']:
                self.var_save_txt.set(False)

        # Filename for HDF5 file
        if self.var_save_txt.get():
            self.hdf5_filename = os.path.splitext(self.entry_save_file.get())[0] + '.h5'
        else:
            self.hdf5_filename = self.entry_save_file.get()

        # Try to open/create file
        try:
            # Create file if it doesn't already exist, append otherwise ('a' parameter)
            with h5py.File(self.hdf5_filename, 'a') as _:
                pass
        except IOError:
            tkMessageBox.showerror('File error', 'Could not create file to save data.')
            self.gui_util('stop')
            return

        # Prepare HDF5 file
        with h5py.File(self.hdf5_filename, 'a') as hdf5_file:
            # Create group for experiment
            # Append to existing file (if applicable). If group already exists, append number to name.
            date = str(now.date())
            subj = self.entry_subject.get() or '?'
            index = 0
            file_index = ''
            while True:
                try:
                    hdf5_grp_exp = hdf5_file.create_group(f'{subj}/{date + file_index}')
                except (RuntimeError, ValueError):
                    index += 1
                    file_index = '-' + str(index)
                else:
                    break
            self.hdf5_grp_name = f'{subj}/{date + file_index}'
            hdf5_grp_exp['weight'] = int(self.entry_weight.get()) if self.entry_weight.get() else 0

            # *** Create file structure ***
            self.cache_size = self.var_cache_size.get()
            nstepframes = 2 * 60000 * self.var_sess_dur.get() / self.var_track_per.get()
            chunk_size = (self.cache_size, 2)

            hdf5_grp_behav = hdf5_grp_exp.create_group('behavior')
            hdf5_grp_behav.create_dataset(name='wheel', dtype='int32', shape=(int(nstepframes) * 1.1, 2), chunks=chunk_size)
            
            # Store session parameters into behavior group
            for key, value in self.parameters.items():
                hdf5_grp_behav.attrs[key] = value.get()

        # Create cache
        self.cache = {
            'wheel': np.zeros((self.cache_size, 2)),
        }

        # Reset counters and clear data
        for counter in self.counter.values(): counter.set(0)
        self.live_view.clear_data()

        # Clear Queues
        for q in [self.q_serial]:
            with q.mutex:
                q.queue.clear()

        # Create thread to scan serial
        suppress = [
            # code_wheel if self.var_suppress_print_movement.get() else None
        ]
        thread_scan = threading.Thread(
            target=scan_serial,
            args=(
                self.q_serial, self.arduino.ser, self.var_print_arduino.get(),
                suppress, code_end
            )
        )
        thread_scan.daemon = True    # Don't remember why this is here

        # Start session
        self.arduino.ser.flushInput()                                   # Remove data from serial input
        self.arduino.ser.write(code_start.encode())
        thread_scan.start()

        self.start_time = datetime.now()
        end_time = self.start_time + timedelta(minutes=self.var_sess_dur.get())
        self.var_start_time.set(self.start_time.strftime('%H:%M:%S'))
        self.var_stop_time.set(end_time.strftime('%H:%M:%S'))
        print('Session start {}'.format(self.start_time))

        # Update GUI
        self.update_session()

    def update_session(self):
        # Checks Queue for incoming data from arduino. Data arrives as comma-
        # separated values with the first element ('code') defining the type of
        # data.

        # Rate to update GUI
        # Should be faster than data coming in, ie tracking rate
        refresh_rate = 10

        # End on 'Stop' button (by user)
        if self.var_stop.get():
            self.var_stop.set(False)
            self.arduino.ser.write('0'.encode())
            print('User triggered stop, sending signal to Arduino...')

        # Watch incoming queue
        # Data has format: [code, ts, extra values]
        # Empty queue before leaving. Otherwise, a backlog will grow.
        while not self.q_serial.empty():
            code, ts, data = self.q_serial.get()
            # print(code, ts, data)

            # End session
            if code == code_end:
                arduino_end = ts
                print('Arduino ended, finalizing data...')
                self.stop_session(arduino_end=arduino_end)
                return

            # Record data to cache
            event_var = arduino_events[code]
            event_n = self.counter[arduino_events[code]].get()
            cache_n = event_n % self.cache_size
            self.cache[event_var][cache_n, :] = [ts, data]
            self.counter[event_var].set(event_n + 1)

            # Record data to HDF5 when cache fills
            if cache_n >= self.cache_size - 1:
                with h5py.File(self.hdf5_filename, 'a') as hdf5_file:
                    cache_slice = slice(event_n - cache_n, event_n + 1)
                    dataset = hdf5_file[f'{self.hdf5_grp_name}/behavior/{event_var}']
                    dataset[cache_slice, :] = self.cache[event_var]
                self.cache[event_var][:] = 0

            # Update live view
            if code == code_wheel:
                self.live_view.update_view(
                    [ts, data],
                    name=arduino_events[code_wheel]
                )

        self.parent.after(refresh_rate, self.update_session)

    def stop_session(self, frame_cutoff=None, arduino_end=None):
        '''Finalize session
        Closes hardware connections and saves HDF5 data file. Resets GUI.
        '''

        end_time = datetime.now().strftime('%H:%M:%S')
        print('Session ended at ' + end_time)
        self.gui_util('stop')
        self.arduino.close_serial()

        # Finalize data
        print('Finalizing behavioral data')
        with h5py.File(self.hdf5_filename, 'a') as hdf5_file:
            # Write remainder of cache
            hdf5_grp_behav = hdf5_file[f'{self.hdf5_grp_name}/behavior']
            hdf5_grp_behav.attrs['start_time'] = self.start_time.strftime('%H:%M:%S')
            hdf5_grp_behav.attrs['end_time'] = end_time
            hdf5_grp_behav.attrs['arduino_end'] = arduino_end
            for ev in arduino_events.values():
                event_n = self.counter[ev].get()
                cache_n = event_n % self.cache_size
                cache_slice = slice(event_n - cache_n, event_n)  # No `+ 1`????????
                dataset = hdf5_grp_behav[ev]
                # pdb.set_trace()
                dataset[cache_slice, :] = self.cache[ev][:cache_n, :]
                dataset.resize((event_n, 2))

            # Write notes
            hdf5_file[self.hdf5_grp_name].attrs['notes'] = \
                self.scrolled_notes.get(1.0, 'end')

        # Create csv files if indicated
        if self.var_save_txt.get():
            filename_base = os.path.splitext(self.entry_save_file.get())[0]

            with h5py.File(self.hdf5_filename, 'r') as hdf5_file:
                hdf5_grp_behav = hdf5_file[f'{self.hdf5_grp_name}/behavior']
                
                # Save attributes
                subj = self.entry_subject.get() or '?'
                wt = hdf5_file[f"{self.hdf5_grp_name}/weight"].value
                notes = hdf5_file[self.hdf5_grp_name].attrs['notes']
                with open(f"{filename_base}-attributes.csv", 'w') as file:
                    file.write(f"subject,{subj}\n")
                    file.write(f"weight,{wt}\n")
                    for k, v in hdf5_grp_behav.attrs.items():
                        file.write(f"{k},{v}\n")
                    file.write(f"notes:\n{notes}")

                # Save datasets
                for ev in arduino_events.values():
                    np.savetxt(
                        f"{filename_base}-{ev}.csv",
                        hdf5_grp_behav[ev],
                        delimiter=','
                    )
            os.remove(self.hdf5_filename)

        # Clear self.parameters
        self.parameters = {}

        # Clear GUI
        self.entry_subject.delete(0, 'end')
        self.entry_weight.delete(0, 'end')
        self.entry_save_file.delete(0, 'end')
        self.scrolled_notes.delete('1.0', 'end')

        print('All done!')
        pdb.set_trace()


def scan_serial(q_serial, ser, print_arduino=False, suppress=[], code_end=0):
    '''Check serial for data
    Continually check serial connection for data sent from Arduino. Send data 
    through Queue to communicate with main GUI. Stop when `code_end` is 
    received from serial.
    '''

    if print_arduino: print('  Scanning Arduino outputs.')
    while 1:
        input_arduino = ser.readline().decode()
        if not input_arduino: continue

        try:
            input_split = [int(x) for x in input_arduino.split(',')]
        except ValueError:
            # If not all comma-separated values are int castable
            if print_arduino: sys.stdout.write(arduino_head + input_arduino)
        else:
            if print_arduino and input_split[0] not in suppress:
                # Only print from serial if code is not in list of codes to suppress
                sys.stdout.write(arduino_head + input_arduino)
            if input_arduino: q_serial.put(input_split)
            if input_split[0] == code_end:
                if print_arduino: print('  Scan complete.')
                return


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--verbose', action='store_true')
    parser.add_argument('--emulate-wheel', action='store_true')
    parser.add_argument('--print-arduino', action='store_true')
    args = parser.parse_args()

    # GUI
    root = tk.Tk()
    root.wm_title('Wheel')
    Main(
        root,
        verbose=args.verbose,
        emulate_wheel=args.emulate_wheel, print_arduino=args.print_arduino
    )
    root.grid()
    root.mainloop()


if __name__ == '__main__':
    main()
