// Lint and simulation stand-in for the Xilinx BUFG (Vivado uses its own).
module BUFG (input wire I, output wire O);
    assign O = I;
endmodule
