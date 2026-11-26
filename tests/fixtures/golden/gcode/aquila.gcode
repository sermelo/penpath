; penpath gcode profile=aquila page=190.000x190.000 page_origin=7.300,0.000 usable_x=0.000..197.300 usable_y=0.000..191.400 z_up=12.500 z_touch=10.000 z_down=9.000
; BEFORE STARTING: paper held down, pen OUT of the clamp. Never home with a pen in.
; touch Z 10.0, pen down Z 9.0, up Z 12.5, offset (-22.7, -28.6)
G21
G90
M104 S0
M140 S0
M107
M84 S0 ; no stepper timeout during the pauses
M201 X500 Y500 Z100
M203 X500 Y500 Z10
M204 P500 T500
M205 X8.00 Y8.00 Z0.40
M300 S1000 P300
M117 Pen OUT? Homing in 10s
G4 S10
G28
M420 S1 Z0 ; saved CR Touch mesh, no fade
G1 Z12.500 F600
; pen change
; ---- pen 1: stabilo_88_black ----
G1 Z12.500 F600
G1 X212.700 Y40.600 F6000
G1 Z10.000 F600
M300 S1000 P300
M117 Pen 1: stabilo_88_black, touch, knob
M0 Pen 1: stabilo_88_black. Touch paper, tighten, press knob
M300 S1500 P200
M117 Plotting stabilo_88_black
G1 Z12.500 F600
; layer 1/1 pen=stabilo_88_black
G0 Z12.500 F600
G0 X39.250 Y208.600 F6000
G0 Z10.500 F600
G1 X40.000 Y208.600 Z10.000 F1500
G1 X41.500 Y208.600 Z9.000
G1 X70.000 Y208.600 Z9.000
G1 X70.000 Y180.100 Z9.000
G1 X70.000 Y178.600 Z10.000
G1 X70.000 Y177.850 Z10.500
G0 Z12.500 F600
G0 X89.250 Y158.600 F6000
G0 Z10.500 F600
G1 X90.000 Y158.600 Z10.000 F1500
G1 X91.500 Y158.600 Z9.000
G1 X118.500 Y158.600 Z9.000
G1 X120.000 Y158.600 Z10.000
G1 X120.750 Y158.600 Z10.500
G0 Z12.500 F600
G1 Z80.000 F600
G1 X0.000 Y220.000 F6000 ; head left, bed forward: paper free to take out
M300 S1500 P150
G4 P200
M300 S1500 P150
M84 S120 ; stepper timeout back to the usual 120 s
M84
M117 Plot done
