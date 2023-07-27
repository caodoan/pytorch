import functools
import itertools
from copy import copy
from typing import List
from unittest.mock import patch

from . import cutlass_utils
from .cuda_kernel import CUDATemplateKernel
from ..common import jinja2_env
from ...ir import Buffer, IRNode, Layout
from ...utils import IndentedBuffer
from ...virtualized import V

from third_party.cutlass.tools.library import scripts as cutlass_lib

class CUDATemplate:
    index_counter = itertools.count()
    all_templates = dict()


    def __init__(self, name: str, input_nodes: List[IRNode], layout: Layout):
        super().__init__()
        self.name = name
        assert name not in self.all_templates, "duplicate template name"
        self.all_templates[name] = self
        self.input_nodes = input_nodes
        self.output_node = Buffer("buf_out", layout)


    @staticmethod
    def _template_from_string(source):
        env = jinja2_env()
        if env is not None:
            return env.from_string(source)
        return None


    def maybe_append_choice(self, choices, **kwargs):
        self.generate(**kwargs)
        pass
        # try:
        #     choices.append(self.generate(**kwargs))
        # except NotImplementedError:
        #     pass


    @staticmethod
    def _fake_get_dtype(fake_out):
        _get_dtype_real = V.graph.get_dtype

        def get_dtype(name):
            if name == fake_out.get_name():
                return fake_out.get_dtype()
            return _get_dtype_real(name)

        return get_dtype


    def _make_kernel_render(self, kernel_name, **kwargs):
        kernel = CUDATemplateKernel(
            kernel_name=kernel_name,
        )
        render = functools.partial(
            self.render,
            kernel=kernel,
            **kwargs,
        )
        return kernel, render


    def generate(self, **kwargs):
        print("generate!")
        kernel_name = f"cuda_{self.name}"
        with patch.object(
            V.graph, "get_dtype", self._fake_get_dtype(self.output_node)
        ), CUDATemplateKernel(
            kernel_name=kernel_name,
        ) as kernel:
            # need to do call render twice to get all the needed args right
            try:
                self.render(kernel=kernel, **kwargs)
                code = self.render(kernel=kernel, **kwargs)
            except ZeroDivisionError:
                # TODO(nmacchioni): fix sympy division by zero
                return None
            print("Generated Code:\n", code)
            # mod = PyCodeCache.load(code, extra)
            # _, call_args, _ = kernel.args.python_argdefs()

        # expected_args = list(unique(x.get_name() for x in input_nodes))
        # expected_args.extend([fake_out.get_name()])
        # assert list(call_args) == expected_args, (call_args, expected_args)
        # extra_args = V.graph.sizevars.size_hints(
        #     map(sympy.expand, call_args[len(expected_args) :])
        # )
        # assert not extra_args, "TODO: dynamic shapes"

        # kernel_hash_name = f"cuda_{self.name}_{next(self.index_counter)}"

        # # create the BenchmarkRequest
        # grid = self.grid(*V.graph.sizevars.size_hints(layout.size), kwargs)
        # bmreq = BenchmarkRequest(
        #     module_path=mod.__file__,
        #     module_cache_key=mod.key,
        #     kernel_name=kernel_name,
        #     grid=grid,
        #     extra_args=extra_args,
        #     num_stages=num_stages,
        #     num_warps=num_warps,
        #     input_tensors=TensorMeta.from_irnodes(input_nodes),
        #     output_tensor=TensorMeta.from_irnodes(layout),
        # )

        # return CUDATemplateCaller(
        #     kernel_hash_name,
        #     input_nodes,
        #     layout,
        #     functools.partial(self._make_kernel_render, input_nodes=input_nodes, kernel_name="KERNEL_NAME"),
        #     bmreq,
        # )
        return None


    def header(self) -> IndentedBuffer:
        res = IndentedBuffer()
        res.splice(
            """
                #include <iostream>
                #include <memory>
                #include <random>
                #include <vector>
            """
        )
        return res


    def globals(self) -> IndentedBuffer:
        res = IndentedBuffer()
        res.splice(
            """
                using bfloat16 = nv_bfloat16;
            """
        )
        return res


    def render(self, **kwargs) -> str:
        raise NotImplementedError


class CutlassTemplate(CUDATemplate):
    def header(self) -> IndentedBuffer:
        res = super().header()
        res.splice(
            """
                #include "cutlass/cutlass.h"
                #include "cutlass/epilogue/collective/collective_builder.hpp"
                #include "cutlass/numeric_types.h"
                #include "cutlass/util/host_tensor.h"
                #include "cutlass/util/reference/host/tensor_fill.h"
                #include "cutlass/util/reference/device/tensor_fill.h"
                #include "cutlass/util/device_memory.h"
            """
        )
        return res

    def globals(self) -> IndentedBuffer:
        res = super().globals()
        res.splice(
            """
                #define CUTLASS_CHECK(status)                                                      \\
                {                                                                                  \\
                  cutlass::Status error = status;                                                  \\
                  if (error != cutlass::Status::kSuccess) {                                        \\
                    auto msg = std::string("[") + __FILE__ + "] Got cutlass error: " +             \\
                        cutlassGetStatusString(error) + " at: " + std::to_string(__LINE__);        \\
                    std::cerr << msg << std::endl;                                                 \\
                    throw std::runtime_error(msg);                                                 \\
                  }                                                                                \\
                }
            """
        )
        return res
