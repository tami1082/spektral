import tensorflow as tf
from tensorflow.keras import activations
from tensorflow.keras import backend as K

from spektral.layers import ops
from spektral.layers.ops import modes
from spektral.layers.pooling.pool import Pool


class DiffPool(Pool):
    r"""
    A DiffPool layer from the paper

    > [Hierarchical Graph Representation Learning with Differentiable Pooling](https://arxiv.org/abs/1806.08804)<br>
    > Rex Ying et al.

    **Mode**: batch.

    This layer computes a soft clustering \(\S\) of the input graphs using a GNN,
    and reduces graphs as follows:
    $$
        \S = \textrm{GNN}(\A, \X); \\
        \A' = \S^\top \A \S; \X' = \S^\top \X;
    $$

    where GNN consists of one GraphConv layer with softmax activation.
    Two auxiliary loss terms are also added to the model: the _link prediction
    loss_
    $$
        \big\| \A - \S\S^\top \big\|_F
    $$
    and the _entropy loss_
    $$
        - \frac{1}{N} \sum\limits_{i = 1}^{N} \S \log (\S).
    $$

    The layer also applies a 1-layer GCN to the input features, and returns
    the updated graph signal (the number of output channels is controlled by
    the `channels` parameter).
    The layer can be used without a supervised loss, to compute node clustering
    simply by minimizing the two auxiliary losses.

    **Input**

    - Node features of shape `([batch], n_nodes, n_node_features)`;
    - Binary adjacency matrix of shape `([batch], n_nodes, n_nodes)`;

    **Output**

    - Reduced node features of shape `([batch], K, channels)`;
    - Reduced adjacency matrix of shape `([batch], K, K)`;
    - If `return_mask=True`, the soft clustering matrix of shape `([batch], n_nodes, K)`.

    **Arguments**

    - `k`: number of nodes to keep;
    - `channels`: number of output channels (if None, the number of output
    channels is assumed to be the same as the input);
    - `return_mask`: boolean, whether to return the cluster assignment matrix;
    - `kernel_initializer`: initializer for the weights;
    - `kernel_regularizer`: regularization applied to the weights;
    - `kernel_constraint`: constraint applied to the weights;
    """

    def __init__(self,
                 k,
                 channels=None,
                 return_mask=False,
                 activation=None,
                 kernel_initializer='glorot_uniform',
                 kernel_regularizer=None,
                 kernel_constraint=None,
                 **kwargs):

        super().__init__(activation=activation,
                         kernel_initializer=kernel_initializer,
                         kernel_regularizer=kernel_regularizer,
                         kernel_constraint=kernel_constraint,
                         **kwargs)
        self.k = k
        self.channels = channels
        self.return_mask = return_mask

    def build(self, input_shape):
        assert isinstance(input_shape, list)
        F = input_shape[0][-1]

        if self.channels is None:
            self.channels = F

        self.kernel_emb = self.add_weight(shape=(F, self.channels),
                                          name='kernel_emb',
                                          initializer=self.kernel_initializer,
                                          regularizer=self.kernel_regularizer,
                                          constraint=self.kernel_constraint)

        self.kernel_pool = self.add_weight(shape=(F, self.k),
                                           name='kernel_pool',
                                           initializer=self.kernel_initializer,
                                           regularizer=self.kernel_regularizer,
                                           constraint=self.kernel_constraint)

        super().build(input_shape)

    def call(self, inputs):
        if len(inputs) == 3:
            X, A, I = inputs
            if K.ndim(I) == 2:
                I = I[:, 0]
        else:
            X, A = inputs
            I = None

        N = K.shape(A)[-1]
        # Check if the layer is operating in mixed or batch mode
        mode = ops.autodetect_mode(A, X)
        self.reduce_loss = mode in (modes.MIXED, modes.BATCH)

        # Get normalized adjacency
        if K.is_sparse(A):
            I_ = tf.sparse.eye(N, dtype=A.dtype)
            A_ = tf.sparse.add(A, I_)
        else:
            I_ = tf.eye(N, dtype=A.dtype)
            A_ = A + I_
        fltr = ops.normalize_A(A_)

        # Node embeddings
        Z = K.dot(X, self.kernel_emb)
        Z = ops.filter_dot(fltr, Z)
        if self.activation is not None:
            Z = self.activation(Z)

        # Compute cluster assignment matrix
        S = K.dot(X, self.kernel_pool)
        S = ops.filter_dot(fltr, S)
        S = activations.softmax(S, axis=-1)  # softmax applied row-wise

        # Link prediction loss
        S_gram = ops.matmul_A_BT(S, S)
        if mode == modes.MIXED:
            A = tf.sparse.to_dense(A)[None, ...]
        if K.is_sparse(A):
            LP_loss = tf.sparse.add(A, -S_gram)  # A/tf.norm(A) - S_gram/tf.norm(S_gram)
        else:
            LP_loss = A - S_gram
        LP_loss = tf.norm(LP_loss, axis=(-1, -2))
        if self.reduce_loss:
            LP_loss = K.mean(LP_loss)
        self.add_loss(LP_loss)

        # Entropy loss
        entr = tf.negative(tf.reduce_sum(tf.multiply(S, K.log(S + K.epsilon())), axis=-1))
        entr_loss = K.mean(entr, axis=-1)
        if self.reduce_loss:
            entr_loss = K.mean(entr_loss)
        self.add_loss(entr_loss)

        # Pooling
        X_pooled = ops.matmul_AT_B(S, Z)
        A_pooled = ops.matmul_AT_B_A(S, A)

        output = [X_pooled, A_pooled]

        if I is not None:
            I_mean = tf.math.segment_mean(I, I)
            I_pooled = ops.repeat(I_mean, tf.ones_like(I_mean) * self.k)
            output.append(I_pooled)

        if self.return_mask:
            output.append(S)

        return output

    @property
    def config(self):
        return {
            'k': self.k,
            'channels': self.channels,
            'return_mask': self.return_mask,
        }
