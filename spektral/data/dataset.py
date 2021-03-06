import copy
import os.path as osp

import numpy as np
import tensorflow as tf

from spektral.data import Graph
from spektral.data.utils import get_spec
from spektral.datasets.utils import DATASET_FOLDER


class Dataset:
    """
    A container for Graph objects. This class can be extended to represent a
    graph dataset.

    Datasets can be accessed with indices (`dataset[0]` returns a `Graph`),
    iterables  (`dataset[[1, 2, 3]]` returns a `Dataset`) or slices
    (`dataset[start:stop]` also returns a `Dataset`).
    They can also be shuffled (`np.random.shuffle(dataset)` shuffles in-place),
    and iterated over (`for graph in dataset: ...`).

    They should generally behave like Numpy arrays for any operation that uses
    simple 1D indexing.

    Datasets have the following properties that automatically computed from the
    graphs:

        - `n_nodes`: the number of nodes in the dataset (always None, except
        when the dataset has only one graph -- i.e., for single mode);
        - `n_node_features`: the size of the node features (assumed to be equal
        for all graphs);
        - `n_edge_features`: the size of the edge features (assumed to be equal
        for all graphs);;
        - `n_labels`: the size of the labels (assumed to be equal for all
        graphs); this is computed as the innermost dimension of the labels
        (i.e., `y.shape[-1]`).

    Any additional `kwargs` passed to the constructor will be automatically
    assigned as instance attributes of the dataset.

    Datasets also offer three main manipulation functions to apply callables to
    their graphs:

    - `apply(transform)`: replaces each graph with the output of
    `transform(graph)`. This should always be a `Graph` object, although no
    checks are made to ensure it (to give you more flexibility). See
    `spektral.transforms` for some ready-to-use transforms.
    For example: `apply(spektral.transforms.NormalizeAdj())` normalizes the
    adjacency matrix of each graph in the dataset.
    - `map(transform, reduce=None)`: returns a list containing the output
    of `transform(graph)` for each graph. If `reduce` is a `callable`, then
    returns `reduce(output_list)` instead of just `output_list`.
    For instance: `map(lambda: g.n_nodes, reduce=np.mean)` will return the
    average number of nodes in the dataset.
    - `filter(function)`: removes from the dataset any graph for which
    `function(graph)` returns `False`.
    For example: `filter(lambda: g.n_nodes < 100)` removes from the dataset all
    graphs bigger than 100 nodes.

    You can extend this class to create your own dataset.
    To create a `Dataset`, you must implement the `Dataset.read()` method, which
    must return a list of `spektral.data.Graph` objects, e.g.,

    ```
    class MyDataset(Dataset):
        def read(self):
            return [Graph(x=x, adj=adj, y=y) for x, adj, y in some_magic_list]
    ```

    The class also offers a `download()` method that is automatically called
    if the path returned by the `Dataset.path` attribute does not exists.
    This defaults to `~/.spektral/datasets/ClassName/`.

    You can implement this however you like, knowing that `download()` will be
    called before `read()`. You can also override the `path` attribute to
    whatever fits your needs.

    Have a look at the `spektral.datasets` module for examples of popular
    datasets already implemented.

    **Arguments**

    - `transforms`: a callable or list of callables that are automatically
    applied to the graphs after loading the dataset.
    """
    def __init__(self, transforms=None, **kwargs):

        # Read extra kwargs
        for k, v in kwargs.items():
            setattr(self, k, v)

        # Download data
        if not osp.exists(self.path):
            self.download()

        # Read graphs
        self.graphs = self.read()
        if len(self.graphs) == 0:
            raise ValueError('Datasets cannot be empty')

        # Apply transforms
        if transforms is not None:
            if not isinstance(transforms, (list, tuple)) and callable(transforms):
                transforms = [transforms]
            elif not all([callable(t) for t in transforms]):
                raise ValueError('`transforms` must be a callable or list of '
                                 'callables')
            else:
                pass
            for t in transforms:
                self.apply(t)

    def read(self):
        raise NotImplementedError

    def download(self):
        pass

    def apply(self, transform):
        if not callable(transform):
            raise ValueError('`transform` must be callable')

        for i in range(len(self.graphs)):
            self.graphs[i] = transform(self.graphs[i])

    def map(self, transform, reduce=None):
        if not callable(transform):
            raise ValueError('`transform` must be callable')
        if reduce is not None and not callable(reduce):
            raise ValueError('`reduce` must be callable')

        out = [transform(g) for g in self.graphs]
        return reduce(out) if reduce is not None else out

    def filter(self, function):
        if not callable(function):
            raise ValueError('`function` must be callable')
        self.graphs = [g for g in self.graphs if function(g)]

    def __getitem__(self, key):
        if not (np.issubdtype(type(key), np.integer) or
                isinstance(key, (slice, list, tuple, np.ndarray))):
            raise ValueError('Unsupported key type: {}'.format(type(key)))
        if np.issubdtype(type(key), np.integer):
            return self.graphs[int(key)]
        else:
            dataset = copy.copy(self)
            if isinstance(key, slice):
                dataset.graphs = self.graphs[key]
            else:
                dataset.graphs = [self.graphs[i] for i in key]
            return dataset

    def __setitem__(self, key, value):
        is_iterable = isinstance(value, (list, tuple))
        if not isinstance(value, (Graph, list, tuple)):
            raise ValueError('Datasets can only be assigned Graphs or '
                             'sequences of Graphs')
        if is_iterable and not all([isinstance(v, Graph) for v in value]):
            raise ValueError('Assigned sequence must contain only Graphs')
        if is_iterable and isinstance(key, int):
            raise ValueError('Cannot assign multiple Graphs to one location')
        if not is_iterable and isinstance(key, (slice, list, tuple)):
            raise ValueError('Cannot assign one Graph to multiple locations')
        if not (isinstance(key, (int, slice, list, tuple))):
            raise ValueError('Unsupported key type: {}'.format(type(key)))

        if isinstance(key, int):
            self.graphs[key] = value
        else:
            if isinstance(key, slice):
                self.graphs[key] = value
            else:
                for i, k in enumerate(key):
                    self.graphs[k] = value[i]

    def __len__(self):
        return len(self.graphs)

    def __repr__(self):
        return '{}(n_graphs={})'.format(self.__class__.__name__, self.n_graphs)

    @property
    def path(self):
        return osp.join(DATASET_FOLDER, self.__class__.__name__)

    @property
    def n_graphs(self):
        return self.__len__()

    @property
    def n_nodes(self):
        if len(self.graphs) == 1:
            return self.graphs[0].n_nodes
        else:
            return None

    @property
    def n_node_features(self):
        if len(self.graphs) >= 1:
            return self.graphs[0].n_node_features
        else:
            return None

    @property
    def n_edge_features(self):
        if len(self.graphs) >= 1:
            return self.graphs[0].n_edge_features
        else:
            return None

    @property
    def n_labels(self):
        if len(self.graphs) >= 1:
            return self.graphs[0].n_labels
        else:
            return None

    @property
    def signature(self):
        """
        This property computes the signature of the dataset, which can be
        passed to `spektral.data.utils.to_tf_signature(signature)` to compute
        the TensorFlow signature. You can safely ignore this property unless
        you are creating a custom `Loader`.

        A signature consist of the TensorFlow TypeSpec, shape, and dtype of
        all characteristic matrices of the graphs in the Dataset. This is
        returned as a dictionary of dictionaries, with keys `x`, `a`, `e`, and
        `y` for the four main data matrices.

        Each sub-dictionary will have keys `spec`, `shape` and `dtype`.
        """
        signature = {}
        graph = self.graphs[0]  # This is always non-empty
        if graph.x is not None:
            signature['x'] = dict()
            signature['x']['spec'] = get_spec(graph.x)
            signature['x']['shape'] = (None, self.n_node_features)
            signature['x']['dtype'] = tf.as_dtype(graph.x.dtype)
        if graph.a is not None:
            signature['a'] = dict()
            signature['a']['spec'] = get_spec(graph.a)
            signature['a']['shape'] = (None, None)
            signature['a']['dtype'] = tf.as_dtype(graph.a.dtype)
        if graph.e is not None:
            signature['e'] = dict()
            signature['e']['spec'] = get_spec(graph.e)
            signature['e']['shape'] = (None, self.n_edge_features)
            signature['e']['dtype'] = tf.as_dtype(graph.e.dtype)
        if graph.y is not None:
            signature['y'] = dict()
            signature['y']['spec'] = get_spec(graph.y)
            signature['y']['shape'] = (self.n_labels,)
            signature['y']['dtype'] = tf.as_dtype(np.array(graph.y).dtype)
        return signature
