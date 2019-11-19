import dclab
from dclab.rtdc_dataset.fmt_hierarchy import RTDC_Hierarchy
import numpy as np

from .. import meta_tool
from .. import util

from .dataslot import Dataslot
from .filter import Filter
from .plot import Plot


class Pipeline(object):
    def __init__(self, state=None):
        self.reset()
        #: Analysis matrix with dataset hierarchies. The first index
        #: identifies the slot and the second index identifies the
        #: filter
        self.matrix = []
        #: used for detecting changes in the matrix
        self._matrix_hash = "None"
        #: holds the slot identifiers of the current matrix
        self._matrix_slots = []
        #: holds the filter identifiers of the current matrix
        self._matrix_filters = []
        #: previous state (see __setstate__)
        self._old_state = {}
        if state is not None:
            self.__setstate__(state)

    def __setstate__(self, state):
        if self._old_state == state:
            # Nothing changed
            return
        self._old_state = state
        self.reset()
        for filt_state in state["filters"]:
            self.add_filter(filt_state)
        self.filters_used = state["filters used"]
        for plot_state in state["plots"]:
            self.add_plot(plot_state)
        for slot_state in state["slots"]:
            self.add_slot(slot=slot_state)
        self.slots_used = state["slots used"]
        # set element states at the end
        self.element_states = state["elements"]

    def __getstate__(self):
        state = {}
        state["elements"] = self.element_states
        state["filters"] = [filt.__getstate__() for filt in self.filters]
        state["filters used"] = self.filters_used
        state["plots"] = [plot.__getstate__() for plot in self.plots]
        state["slots"] = [slot.__getstate__() for slot in self.slots]
        state["slots used"] = self.slots_used
        return state

    @property
    def filter_ids(self):
        return [filt.identifier for filt in self.filters]

    @property
    def plot_ids(self):
        return [plot.identifier for plot in self.plots]

    @property
    def slot_ids(self):
        return [slot.identifier for slot in self.slots]

    @property
    def num_filters(self):
        return len(self.filters)

    @property
    def num_plots(self):
        return len(self.filters)

    @property
    def num_slots(self):
        return len(self.slots)

    @property
    def paths(self):
        return [ds.path for ds in self.slots]

    def add_filter(self, filt=None, index=None):
        """Add a filter to the pipeline

        Parameters
        ----------
        filt: shapeout2.pipeline.Filter or dict
            Filter instance or its state from Filter.__getstate__()
        index: int
            Position in the filter list, defaults to `len(self.filters)`

        Returns
        -------
        index: int
            index of the filter in the pipeline;
            indexing starts at "0".
        """
        if index is None:
            index = len(self.filters)
        if filt is None:
            filt = Filter()
        elif isinstance(filt, Filter):
            pass
        elif isinstance(filt, dict):
            state = filt
            if state["identifier"] in Filter._instances:
                filt = Filter._instances[filt["identifier"]]
            else:
                filt = Filter()
            filt.__setstate__(state)
        self.filters.insert(index, filt)
        filt_id = filt.identifier
        for slot_id in self.slot_ids:
            self.element_states[slot_id][filt_id] = False
        self.filters_used.append(filt_id)
        return filt_id

    def add_plot(self, plot=None, index=None):
        """Add a filter to the pipeline

        Parameters
        ----------
        plot: shapeout2.pipeline.Plot or dict
            Plot instance or its state from Plot.__getstate__()
        index: int
            Position in the plot list, defaults to `len(self.plots)`

        Returns
        -------
        index: int
            index of the plot in the pipeline;
            indexing starts at "0".
        """
        if index is None:
            index = len(self.plots)
        if plot is None:
            plot = Plot()
        elif isinstance(plot, Plot):
            pass
        elif isinstance(plot, dict):
            state = plot
            if state["identifier"] in Plot._instances:
                plot = Plot._instances[plot["identifier"]]
            else:
                plot = Plot()
            plot.__setstate__(state)

        self.plots.insert(index, plot)
        plot_id = plot.identifier
        for slot_id in self.slot_ids:
            self.element_states[slot_id][plot_id] = False

        return plot.identifier

    def add_slot(self, slot=None, path=None, index=None):
        """Add a slot (experiment) to the pipeline

        Parameters
        ----------
        slot: shapeout2.pipeline.Dataslot or dict
            Dataslot representing an experimental dataset or its
            state from Dataslot.__getstate__()
        path: str or pathlib.Path
            Path to a measurement
        index: int
            Position in the slot list, defaults to `len(self.slots)`

        Returns
        -------
        index: int
            index of the slot in the pipeline;
            indexing starts at "0".
        identifier: str
            identifier of the slot
        """
        if index is None:
            index = len(self.slots)
        if ((slot is None and path is None)
                or (slot is not None and path is not None)):
            raise ValueError("Please specify either `slot` or `path`.")
        elif path is not None:
            slot = Dataslot(path=path)
        elif isinstance(slot, Dataslot):
            pass
        elif isinstance(slot, dict):
            state = slot
            if state["identifier"] in Dataslot._instances:
                slot = Dataslot._instances[slot["identifier"]]
            else:
                slot = Dataslot()
            slot.__setstate__(state)

        self.slots.insert(index, slot)
        slot_id = slot.identifier
        self.element_states[slot_id] = {}
        for filt_id in self.filter_ids:
            self.element_states[slot_id][filt_id] = False
        self.slots_used.append(slot_id)

        # check that the features are all the same
        f0 = meta_tool.get_rtdc_features(self.slots[0].path)
        fi = meta_tool.get_rtdc_features(slot.path)
        if f0 != fi:
            # This is important for updating the filter min/max values
            # TODO:
            # - ignore features that are not shared among all datasets
            raise ValueError("Currently, only RT-DC measurements with the "
                             + "same scalar features are allowed - Sorry. "
                             + "Please create an issue if you need this.")
        return slot.identifier

    def construct_matrix(self):
        """Construct the pipeline matrix

        This generates dataset hierarchies and updates
        the filters.
        """
        # TODO:
        # - incremental updates
        matrix_filters = [filt.identifier for filt in self.filters]
        matrix_slots = [slot.identifier for slot in self.slots]
        matrix_hash = util.hashobj([matrix_slots, matrix_filters])
        n_filt_then = len(self._matrix_filters)
        if self._matrix_hash != matrix_hash:
            matrix = []
            if self._matrix_filters == matrix_filters:
                # only a slot was added/removed
                for sl in self.slots:
                    # find it in the old matrix
                    for row in self.matrix:
                        if row[0].identifier == sl.identifier:
                            # use this row
                            break
                    else:
                        # new dataset
                        ds = dclab.new_dataset(sl.path,
                                               identifier=sl.identifier)
                        sl.update_dataset(ds)
                        row = [ds]
                        for _ in self.filters:
                            # generate hierarchy children
                            ds = RTDC_Hierarchy(hparent=ds,
                                                apply_filter=False)
                            row.append(ds)
                    matrix.append(row)
            elif (self._matrix_slots == matrix_slots
                  and self._matrix_filters == matrix_filters[:n_filt_then]):
                # only a filter was added
                matrix = self.matrix
                for ii, sl in enumerate(self.slots):
                    row = matrix[ii]
                    for _ in self.filters[n_filt_then:]:
                        ds = RTDC_Hierarchy(hparent=row[-1],
                                            apply_filter=False)
                        row.append(ds)
            else:
                # everything changed
                for sl in self.slots:
                    ds = dclab.new_dataset(sl.path, identifier=sl.identifier)
                    row = [ds]
                    for _ in self.filters:
                        # generate hierarchy children
                        ds = RTDC_Hierarchy(hparent=ds,
                                            apply_filter=False)
                        row.append(ds)
                    matrix.append(row)

            self.matrix = matrix
            self._matrix_hash = matrix_hash
            self._matrix_slots = matrix_slots
            self._matrix_filters = matrix_filters
            # TODO:
            # - if `self.elements_dict` is not complete, autocomplete it
            #   (as it is done in gui.matrix.dm_dataset)

    def get_dataset(self, slot_index, filt_index, apply_filter=True,
                    ret_color=False):
        """Return dataset with all filters updated (optionally applied)

        Parameters
        ----------
        slot_index: int
            index of measurement
        filt_index: int
            index of filter
        apply_filter: bool
            whether to call `dataset.apply_filter` in the end;
            if set to `False`, only the filtering configuration
            of the dataset and its hierarchy parents are updated
        ret_color: bool
            also return the color of the dataset as a string
        """
        self.construct_matrix()
        row = self.matrix[slot_index]
        slot = self.slots[slot_index]
        fstates = self.element_states[slot.identifier]
        # set all necessary filters
        for ii in range(filt_index + 1):
            filt = self.filters[ii]
            filt_id = filt.identifier
            # TODO:
            # - cache previously filter states and compare to new filter
            #   states to avoid recomputation when `apply_filter`
            #   is called.
            # these are the element states in gui.matrix.dm_element
            if fstates[filt_id] and filt_id in self.filters_used:
                filt.update_dataset(row[ii])
            else:
                row[ii].config["filtering"]["enable filters"] = False
        dsend = row[filt_index]
        # update configuration from slot
        slot.update_dataset(dsend)
        if apply_filter:
            dsend.apply_filter()
        if ret_color:
            return dsend, slot.color
        else:
            return dsend

    def get_features(self, scalar=False, label_sort=False):
        """Return a list of features that all slots share"""
        if scalar:
            features = dclab.dfn.scalar_feature_names
        else:
            features = dclab.dfn.feature_names
        for slot_index in range(self.num_slots):
            ds = self.get_dataset(slot_index=slot_index,
                                  filt_index=0,
                                  apply_filter=False)
            features = sorted(set(ds.features) & set(features))
        if label_sort:
            labs = [dclab.dfn.feature_name2label[f] for f in features]
            lf = sorted(zip(labs, features))
            features = [it[1] for it in lf]
        return features

    def get_min_max(self, feat):
        fmin = np.inf
        fmax = -np.inf
        for slot_index in range(self.num_slots):
            ds = self.get_dataset(slot_index=slot_index,
                                  filt_index=0,
                                  apply_filter=False)
            vmin = np.nanmin(ds[feat])
            vmax = np.nanmax(ds[feat])
            fmin = np.min([fmin, vmin])
            fmax = np.max([fmax, vmax])
        return [fmin, fmax]

    def get_plot_datasets(self, plot_id):
        """Return a list of datasets with slot states that belong to a plot"""
        datasets = []
        states = []
        filt_index = self.num_filters - 1
        # keep the same order as in self.slots
        for slot_index in range(len(self.slots)):
            slot = self.slots[slot_index]
            slot_id = slot.identifier
            if (self.element_states[slot_id][plot_id]
                    and slot_id in self.slots_used):
                ds = self.get_dataset(slot_index=slot_index,
                                      filt_index=filt_index,
                                      apply_filter=True)
                datasets.append(ds)
                states.append(slot.__getstate__())
        return datasets, states

    def get_slot(self, slot_id):
        """Return the Dataslot matching the RTDCBase identifier"""
        self.construct_matrix()
        for slot, row in zip(self.slots, self.matrix):
            ids = [ds.identifier for ds in row]
            if slot_id in ids:
                break
        else:
            raise ValueError("Unknown dataset identifier: "
                             + "`{}`".format(slot_id))
        return slot

    def remove_filter(self, filt_id):
        """Remove a filter by filter identifier"""
        index = self.filter_ids.index(filt_id)
        self.filters.pop(index)
        if filt_id in self.filters_used:
            self.filters_used.remove(filt_id)
        for slot_id in self.element_states:
            if filt_id in self.element_states[slot_id]:
                self.element_states[slot_id].pop(filt_id)

    def remove_plot(self, plot_id):
        """Remove a filter by plot identifier"""
        index = self.plot_ids.index(plot_id)
        self.plots.pop(index)
        for slot_id in self.element_states:
            if plot_id in self.element_states[slot_id]:
                self.element_states[slot_id].pop(plot_id)

    def remove_slot(self, slot_id):
        """Remove a slot by slot identifier"""
        index = self.filter_ids.index(slot_id)
        self.filters.pop(index)
        if slot_id in self.plots_used:
            self.plots_used.remove(slot_id)
        if slot_id in self.element_states:
            self.element_states.pop(slot_id)

    def reset(self):
        """Reset the pipeline"""
        #: Filters are instances of :class:`shapeout2.pipeline.Filter`
        self.filters = []
        #: List of identifiers for filters that are used
        self.filters_used = []
        #: Plots are instances of :class:`shapeout2.pipeline.Plot`
        self.plots = []
        #: Slots are instances of :class:`shapeout2.pipeline.Dataslot`
        self.slots = []
        #: List of identifiers for slots that are used
        self.slots_used = []
        #: individual element states
        self.element_states = {}
