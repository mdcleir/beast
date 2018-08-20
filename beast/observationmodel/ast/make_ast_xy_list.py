from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import numpy as np

from astropy.io import ascii, fits
from astropy.table import Column, Table
from astropy.wcs import WCS

from ...tools.pbar import Pbar
from ...tools import density_map


def pick_positions_from_map(chosen_seds, input_map, N_bins, Npermodel,
                            outfile=None, refimage=None, Nrealize=1):
    """
    Spreads a set of fake stars across regions of similar values, 
    given a map file generated by 'create background density map' or
    'create stellar density map' in the tools directory.

    The tiles of the given map are divided across a given
    number of bins. Each bin will then have its own set of tiles, 
    which constitute a region on the image.

    Then, for each bin, the given set of fake stars is duplicated, 
    and the stars are assigned random positions within this region.

    This way, it can be ensured that enough ASTs are performed for each
    regime of the map, making it possible to have a separate noise model 
    for each of these regions.

    Parameters
    ----------

    chosen_seds: astropy Table
        Table containing fake stars to be duplicated and assigned positions

    input_map: str
        Path to a hd5 file containing the file written by a DensityMap

    N_bins: int
        The number of bins for the range of background density values.
        The bins will be picked on a linear grid, ranging from the
        minimum to the maximum value of the map. Then, each
        tile will be put in a bin, so that a set of tiles of the map is
        obtained for each range of background density values.

    refimage: str
        Path to fits image that is used for the positions. If none is
        given, the ra and dec will be put in the x and y output columns
        instead.

    Nrealize: integer
        The number of times each model should be repeated for each
        background regime. This is to sample the variance due to
        variations within each region, for each individual model.

    Returns
    -------
    astropy Table: List of fake stars, with magnitudes and positions
    - optionally -
    ascii file of this table, written to outfile

    """

    # Load the background map
    print(Npermodel, ' repeats of each model in each map bin')

    bdm = density_map.BinnedDensityMap.create(input_map, N_bins)
    tile_vals = bdm.tile_vals()
    max_val = np.amax(tile_vals)
    min_val = np.amin(tile_vals)
    tiles_foreach_bin = bdm.tiles_foreach_bin()

    # Remove empty bins
    tile_sets = [tile_set for tile_set in tiles_foreach_bin if len(tile_set)]
    print(len(tile_sets), ' non-empty map bins found between ', min_val, 'and', max_val)

    # Repeat the seds Nrealize times (sample each on at Nrealize
    # different positions, in each region)
    repeated_seds = np.repeat(chosen_seds, Nrealize)
    Nseds_per_region = len(repeated_seds)
    # For each set of tiles, repeat the seds and spread them evenly over
    # the tiles
    repeated_seds = np.repeat(repeated_seds, len(tile_sets))

    out_table = Table(repeated_seds, names=chosen_seds.colnames)
    xs = np.zeros(len(out_table))
    ys = np.zeros(len(out_table))
    bin_indices = np.zeros(len(out_table))

    tile_ra_min, tile_dec_min = bdm.min_ras_decs()
    tile_ra_delta, tile_dec_delta = bdm.delta_ras_decs()

    if refimage is None:
        wcs = None
    else:
        imagehdu = fits.open(refimage)[1]
        wcs = WCS(imagehdu.header)

    pbar = Pbar(len(tile_sets),
                desc='{} models per map bin'.format(Nseds_per_region/Npermodel))
    for bin_index, tile_set in pbar.iterover(enumerate(tile_sets)):
        start = bin_index * Nseds_per_region
        stop = start + Nseds_per_region
        bin_indices[start:stop] = bin_index
        for i in range(Nseds_per_region):
            x = -1
            y = -1
            # Convert each ra,dec to x,y. If there are negative values, try again
            while x < 0 or y < 0:
                # Pick a random tile
                tile = np.random.choice(tile_set)
                # Within this tile, pick a random ra and dec
                ra = tile_ra_min[tile] + \
                     np.random.random_sample() * tile_ra_delta[tile]
                dec = tile_dec_min[tile] + \
                      np.random.random_sample() * tile_dec_delta[tile]

                if wcs is None:
                    x, y = ra, dec
                    break
                else:
                    [x], [y] = wcs.all_world2pix(np.array([ra]), np.array([dec]), 0)

            j = bin_index * Nseds_per_region + i
            xs[j] = x
            ys[j] = y


    # I'm just mimicking the format that is produced by the examples
    cs = []
    cs.append(Column(np.zeros(len(out_table), dtype=int), name='zeros'))
    cs.append(Column(np.ones(len(out_table), dtype=int), name='ones'))

    if wcs is None:
        cs.append(Column(xs, name='RA'))
        cs.append(Column(ys, name='DEC'))
    else:
        cs.append(Column(xs, name='X'))
        cs.append(Column(ys, name='Y'))

    for i, c in enumerate(cs):
        out_table.add_column(c, index=i)  # insert these columns from the left

    # Write out the table in ascii
    if outfile:
        formats = {k: '%.5f' for k in out_table.colnames[2:]}
        ascii.write(out_table, outfile, overwrite=True, formats=formats)

    return out_table


def pick_positions(catalog, filename, separation, refimage=None):
    """
    Assigns positions to fake star list generated by pick_models

    INPUTS:
    -------

    filename:   string
                Name of AST list generated by pick_models
    separation: float
                Minimum pixel separation between AST and star in photometry 
                catalog provided in the datamodel.
    refimage:   Name of the reference image.  If supplied, the method will use the 
                reference image header to convert from RA and DEC to X and Y.

    OUTPUTS:
    --------

    Ascii table that replaces [filename] with a new version of
    [filename] that contains the necessary position columns for running
    the ASTs though DOLPHOT
    """

    noise = 3.0 #Spreads the ASTs in a circular annulus of 3 pixel width instead of all being 
                #precisely [separation] from an observed star.

    colnames = catalog.data.columns    

    if 'X' or 'x' in colnames:
        if 'X' in colnames:
           x_positions = catalog.data['X'][:]
           y_positions = catalog.data['Y'][:]
        if 'x' in colnames:
           x_positions = catalog.data['x'][:]
           y_positions = catalog.data['y'][:]
    else:
        if refimage:
            if 'RA' or 'ra' in colnames:
                if 'RA' in colnames:
                    ra_positions = catalog.data['RA'][:]
                    dec_positions = catalog.data['DEC'][:]
                if 'ra' in colnames:
                    ra_positions = catalog.data['ra'][:]
                    dec_positions = catalog.data['dec'][:]
            else:
                raise RuntimeError("Your catalog does not supply X, Y or RA, DEC information for spatial AST distribution")

        else:
            raise RuntimeError("You must supply a Reference Image to determine spatial AST distribution.")
        wcs = WCS(refimage)
        x_positions,y_positions = wcs.all_world2pix(ra_positions,dec_positions,0)
 
    astmags = ascii.read(filename)

    n_asts = len(astmags)

    # keep is defined to ensure that no fake stars are put outside of the image boundaries

    keep = (x_positions > np.min(x_positions) + separation + noise) & (x_positions < np.max(x_positions) - separation - noise) & \
           (y_positions > np.min(y_positions) + separation + noise) & (y_positions < np.max(y_positions) - separation - noise)

    x_positions = x_positions[keep]
    y_positions = y_positions[keep]

    ncat = len(x_positions)
    ind = np.random.random(n_asts)*ncat
    ind = ind.astype('int')


    # Here we generate the circular distribution of ASTs surrounding random observed stars
 
    separation = np.random.random(n_asts)*noise + separation
    theta = np.random.random(n_asts) * 2.0 * np.pi
    xvar = separation * np.cos(theta)
    yvar = separation * np.sin(theta)
    
    new_x = x_positions[ind]+xvar; new_y = y_positions[ind]+yvar
    column1 = 0 * new_x
    column2 = column1 + 1
    column1 = Column(name='zeros',data=column1.astype('int'))
    column2 = Column(name='ones',data=column2.astype('int'))
    column3 = Column(name='X',data=new_x,format='%.2f')
    column4 = Column(name='Y',data=new_y,format='%.2f')
    astmags.add_column(column1,0)
    astmags.add_column(column2,1)
    astmags.add_column(column3,2)
    astmags.add_column(column4,3)
    
    ascii.write(astmags,filename,overwrite=True)
    
