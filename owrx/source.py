import subprocess
from owrx.config import PropertyManager
import threading
import csdr
import time

class RtlNmuxSource(object):
    def __init__(self):
        pm = PropertyManager.getSharedInstance()

        nmux_bufcnt = nmux_bufsize = 0
        while nmux_bufsize < pm.getPropertyValue("samp_rate")/4: nmux_bufsize += 4096
        while nmux_bufsize * nmux_bufcnt < pm.getPropertyValue("nmux_memory") * 1e6: nmux_bufcnt += 1
        if nmux_bufcnt == 0 or nmux_bufsize == 0:
            print("[openwebrx-main] Error: nmux_bufsize or nmux_bufcnt is zero. These depend on nmux_memory and samp_rate options in config_webrx.py")
            return
        print("[openwebrx-main] nmux_bufsize = %d, nmux_bufcnt = %d" % (nmux_bufsize, nmux_bufcnt))
        cmd = pm.getPropertyValue("start_rtl_command") + "| nmux --bufsize %d --bufcnt %d --port %d --address 127.0.0.1" % (nmux_bufsize, nmux_bufcnt, pm.getPropertyValue("iq_server_port"))
        subprocess.Popen(cmd, shell=True)
        print("[openwebrx-main] Started rtl source: " + cmd)

class SpectrumThread(threading.Thread):
    sharedInstance = None
    @staticmethod
    def getSharedInstance():
        if SpectrumThread.sharedInstance is None:
            SpectrumThread.sharedInstance = SpectrumThread()
            SpectrumThread.sharedInstance.start()
        return SpectrumThread.sharedInstance

    def __init__(self):
        self.clients = []
        self.doRun = True
        super().__init__()

    def run(self):
        pm = PropertyManager.getSharedInstance()

        samp_rate = pm.getPropertyValue("samp_rate")
        fft_size = pm.getPropertyValue("fft_size")
        fft_fps = pm.getPropertyValue("fft_fps")
        fft_voverlap_factor = pm.getPropertyValue("fft_voverlap_factor")
        fft_compression = pm.getPropertyValue("fft_compression")
        format_conversion = pm.getPropertyValue("format_conversion")

        spectrum_dsp=dsp=csdr.dsp()
        dsp.nc_port = pm.getPropertyValue("iq_server_port")
        dsp.set_demodulator("fft")
        dsp.set_samp_rate(samp_rate)
        dsp.set_fft_size(fft_size)
        dsp.set_fft_fps(fft_fps)
        dsp.set_fft_averages(int(round(1.0 * samp_rate / fft_size / fft_fps / (1.0 - fft_voverlap_factor))) if fft_voverlap_factor>0 else 0)
        dsp.set_fft_compression(fft_compression)
        dsp.set_format_conversion(format_conversion)
        dsp.csdr_dynamic_bufsize = pm.getPropertyValue("csdr_dynamic_bufsize")
        dsp.csdr_print_bufsizes = pm.getPropertyValue("csdr_print_bufsizes")
        dsp.csdr_through = pm.getPropertyValue("csdr_through")
        sleep_sec=0.87/fft_fps
        print("[openwebrx-spectrum] Spectrum thread initialized successfully.")
        dsp.start()
        if pm.getPropertyValue("csdr_dynamic_bufsize"):
            dsp.read(8) #dummy read to skip bufsize & preamble
            print("[openwebrx-spectrum] Note: CSDR_DYNAMIC_BUFSIZE_ON = 1")
        print("[openwebrx-spectrum] Spectrum thread started.")
        bytes_to_read=int(dsp.get_fft_bytes_to_read())
        spectrum_thread_counter=0
        while self.doRun:
            data=dsp.read(bytes_to_read)
            #print("gotcha",len(data),"bytes of spectrum data via spectrum_thread_function()")
            if spectrum_thread_counter >= fft_fps:
                spectrum_thread_counter=0
            else: spectrum_thread_counter+=1
            for c in self.clients:
                c.write_spectrum_data(data)

        print("spectrum thread shut down")

    def add_client(self, c):
        self.clients.append(c)

    def remove_client(self, c):
        self.clients.remove(c)
        if not self.clients:
            self.shutdown()

    def shutdown(self):
        print("shutting down spectrum thread")
        SpectrumThread.sharedInstance = None
        self.doRun = False

class DspManager(object):
    def __init__(self, handler):
        self.doRun = True
        self.handler = handler

        pm = PropertyManager.getSharedInstance()

        self.dsp = csdr.dsp()
        #dsp_initialized=False
        pm.getProperty("audio_compression").wire(self.dsp.set_audio_compression)
        pm.getProperty("fft_compression").wire(self.dsp.set_fft_compression)
        pm.getProperty("format_conversion").wire(self.dsp.set_format_conversion)
        self.dsp.set_offset_freq(0)
        self.dsp.set_bpf(-4000,4000)
        pm.getProperty("digimodes_fft_size").wire(self.dsp.set_secondary_fft_size)

        self.dsp.nc_port=pm.getPropertyValue("iq_server_port")
        self.dsp.csdr_dynamic_bufsize = pm.getPropertyValue("csdr_dynamic_bufsize")
        self.dsp.csdr_print_bufsizes = pm.getPropertyValue("csdr_print_bufsizes")
        self.dsp.csdr_through = pm.getPropertyValue("csdr_through")

        pm.getProperty("samp_rate").wire(self.dsp.set_samp_rate)
        #do_secondary_demod=False

        self.localProps = PropertyManager()
        self.localProps.getProperty("output_rate").wire(self.dsp.set_output_rate)
        self.localProps.getProperty("offset_freq").wire(self.dsp.set_offset_freq)
        self.localProps.getProperty("squelch_level").wire(self.dsp.set_squelch_level)

        def set_low_cut(cut):
            bpf = self.dsp.get_bpf()
            bpf[0] = cut
            self.dsp.set_bpf(*bpf)
        self.localProps.getProperty("low_cut").wire(set_low_cut)

        def set_high_cut(cut):
            bpf = self.dsp.get_bpf()
            bpf[1] = cut
            self.dsp.set_bpf(*bpf)
        self.localProps.getProperty("high_cut").wire(set_high_cut)

        def set_mod(mod):
            if (self.dsp.get_demodulator() == mod): return
            self.dsp.stop()
            self.dsp.set_demodulator(mod)
            self.dsp.start()
        self.localProps.getProperty("mod").wire(set_mod)

        if (pm.getPropertyValue("digimodes_enable")):
            def set_secondary_mod(mod):
                self.dsp.stop()
                if mod == False:
                    self.dsp.set_secondary_demodulator(None)
                else:
                    self.dsp.set_secondary_demodulator(mod)
                    # TODO frontend will probably miss this
                    #rxws.send(self, "MSG secondary_fft_size={0} if_samp_rate={1} secondary_bw={2} secondary_setup".format(cfg.digimodes_fft_size, dsp.if_samp_rate(), dsp.secondary_bw()))
                self.dsp.start()

            self.localProps.getProperty("secondary_mod").wire(set_secondary_mod)

            self.localProps.getProperty("secondary_offset_freq").wire(self.dsp.set_secondary_offset_freq)

        super().__init__()

    def start(self):
        self.dsp.start()
        threading.Thread(target = self.readDspOutput).start()
        threading.Thread(target = self.readSMeterOutput).start()

    def readDspOutput(self):
        while (self.doRun):
            data = self.dsp.read(256)
            self.handler.write_dsp_data(data)

    def readSMeterOutput(self):
        while (self.doRun):
            level = self.dsp.get_smeter_level()
            self.handler.write_s_meter_level(level)

    def stop(self):
        self.doRun = False
        self.dsp.stop()

    def setProperty(self, prop, value):
        self.localProps.getProperty(prop).setValue(value)

class CpuUsageThread(threading.Thread):
    sharedInstance = None
    @staticmethod
    def getSharedInstance():
        if CpuUsageThread.sharedInstance is None:
            CpuUsageThread.sharedInstance = CpuUsageThread()
            CpuUsageThread.sharedInstance.start()
        return CpuUsageThread.sharedInstance

    def __init__(self):
        self.clients = []
        self.doRun = True
        self.last_worktime = 0
        self.last_idletime = 0
        super().__init__()

    def run(self):
        while self.doRun:
            time.sleep(3)
            try:
                cpu_usage = self.get_cpu_usage()
            except:
                cpu_usage = 0
            for c in self.clients:
                c.write_cpu_usage(cpu_usage)
        print("cpu usage thread shut down")

    def get_cpu_usage(self):
        try:
            f = open("/proc/stat","r")
        except:
            return 0 #Workaround, possibly we're on a Mac
        line = ""
        while not "cpu " in line: line=f.readline()
        f.close()
        spl = line.split(" ")
        worktime = int(spl[2]) + int(spl[3]) + int(spl[4])
        idletime = int(spl[5])
        dworktime = (worktime - self.last_worktime)
        didletime = (idletime - self.last_idletime)
        rate = float(dworktime) / (didletime+dworktime)
        self.last_worktime = worktime
        self.last_idletime = idletime
        if (self.last_worktime==0): return 0
        return rate

    def add_client(self, c):
        self.clients.append(c)

    def remove_client(self, c):
        self.clients.remove(c)
        if not self.clients:
            self.shutdown()

    def shutdown(self):
        print("shutting down cpu usage thread")
        CpuUsageThread.sharedInstance = None
        self.doRun = False
